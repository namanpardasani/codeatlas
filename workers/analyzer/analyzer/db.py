import json

import psycopg
import redis
from psycopg.types.json import Jsonb

from . import config
from .inventory import FileRecord
from .parsing.aggregate import file_aggregates
from .textutil import expand_identifiers
from .parsing.types import ParseResult


def connect() -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL, autocommit=True)


def get_job(conn: psycopg.Connection, job_id: int):
    return conn.execute(
        """SELECT j.id, j.repo_id, j.status, j.attempts, r.url
           FROM analysis_jobs j JOIN repos r ON r.id = j.repo_id WHERE j.id = %s""",
        (job_id,),
    ).fetchone()


def start_job(conn: psycopg.Connection, job_id: int) -> int:
    row = conn.execute(
        """UPDATE analysis_jobs SET status='running', attempts = attempts + 1,
           started_at = COALESCE(started_at, now()), error = NULL
           WHERE id = %s RETURNING attempts""",
        (job_id,),
    ).fetchone()
    return row[0]


def update_progress(conn, r: redis.Redis, job_id: int, stage: str, progress: int,
                    status: str = "running", error: str | None = None, commit_sha: str | None = None):
    finished = status in ("done", "failed")
    conn.execute(
        """UPDATE analysis_jobs SET status=%s, stage=%s, progress=%s, error=%s,
           commit_sha = COALESCE(%s, commit_sha),
           finished_at = CASE WHEN %s THEN now() ELSE finished_at END
           WHERE id = %s""",
        (status, stage, progress, error, commit_sha, finished, job_id),
    )
    r.publish(config.events_channel(job_id), json.dumps(
        {"id": job_id, "status": status, "stage": stage, "progress": progress, "error": error}))


def set_repo_status(conn, repo_id: int, status: str, commit_sha: str | None = None):
    conn.execute(
        "UPDATE repos SET status=%s, last_commit_sha = COALESCE(%s, last_commit_sha) WHERE id=%s",
        (status, commit_sha, repo_id),
    )


def save_files(conn: psycopg.Connection, repo_id: int, commit_sha: str,
               records: list[FileRecord]) -> dict[str, int]:
    """Idempotent: upsert on (repo_id, path), then drop files that no longer exist."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO files (repo_id, path, language, size, lines, content_hash, commit_sha, is_test)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (repo_id, path) DO UPDATE SET
                     language=EXCLUDED.language, size=EXCLUDED.size, lines=EXCLUDED.lines,
                     content_hash=EXCLUDED.content_hash, commit_sha=EXCLUDED.commit_sha,
                     is_test=EXCLUDED.is_test""",
                [(repo_id, f.path, f.language, f.size, f.lines, f.content_hash, commit_sha, f.is_test)
                 for f in records],
            )
            cur.execute(
                "DELETE FROM files WHERE repo_id = %s AND NOT (path = ANY(%s))",
                (repo_id, [f.path for f in records]),
            )
    return {path: fid for fid, path in conn.execute(
        "SELECT id, path FROM files WHERE repo_id = %s", (repo_id,)).fetchall()}


def save_parse_results(conn: psycopg.Connection, repo_id: int,
                       results: dict[int, ParseResult]) -> None:
    """Replace a repo's parse output atomically. Idempotent: re-running yields identical rows,
    never duplicates (delete-then-insert in one transaction + UNIQUE (file_id, idx))."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM symbols WHERE repo_id = %s", (repo_id,))
            cur.execute("DELETE FROM imports_raw WHERE repo_id = %s", (repo_id,))
            cur.executemany(
                """UPDATE files SET parse_status=%s, parse_error=%s, exports=%s,
                          code_lines=%s, comment_lines=%s, comment_ratio=%s, total_complexity=%s,
                          max_complexity=%s, max_nesting=%s, function_count=%s, longest_function=%s
                   WHERE id=%s""",
                [(r.status, r.error, Jsonb(r.exports),
                  r.metrics.code_lines if r.metrics else None, r.metrics.comment_lines if r.metrics else None,
                  r.metrics.comment_ratio if r.metrics else None,
                  *((a["total_complexity"], a["max_complexity"], a["max_nesting"], a["function_count"],
                     a["longest_function"]) if r.metrics else (None,) * 5),
                  fid) for fid, r in ((fid, r) for fid, r in results.items()) for a in [file_aggregates(r)]],
            )
            cur.executemany(
                """INSERT INTO symbols (repo_id, file_id, idx, name, kind, start_line, end_line, params,
                                        parent_name, is_exported, is_default_export, has_doc, signature,
                                        complexity, max_nesting, param_count)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(repo_id, fid, i, s.name, s.kind, s.start_line, s.end_line, Jsonb(s.params),
                  s.parent, s.is_exported, s.is_default_export, s.has_doc, s.signature,
                  s.complexity, s.max_nesting if s.complexity is not None else None, s.param_count)
                 for fid, r in results.items() for i, s in enumerate(r.symbols)],
            )
            cur.executemany(
                """INSERT INTO imports_raw (repo_id, file_id, idx, specifier, kind, names, level, line, is_type_only)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(repo_id, fid, i, im.specifier, im.kind, Jsonb(im.names), im.level, im.line, im.is_type_only)
                 for fid, r in results.items() for i, im in enumerate(r.imports)],
            )


def save_resolutions(conn: psycopg.Connection, repo_id: int, file_ids: dict[str, int],
                     resolutions) -> None:
    """Attach resolution results to imports_raw rows (matched on file_id + idx). Idempotent."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                """UPDATE imports_raw SET resolution=%s, targets=%s, package=%s, reason=%s
                   WHERE repo_id=%s AND file_id=%s AND idx=%s""",
                [(r.resolution.status, Jsonb(r.resolution.targets), r.resolution.package,
                  r.resolution.reason, repo_id, file_ids[r.from_path], r.idx)
                 for r in resolutions],
            )


def save_graph(conn: psycopg.Connection, repo_id: int, file_ids: dict[str, int], analysis, edges) -> None:
    """Replace a repo's graph atomically (idempotent): dependencies, cycles, module edges and the
    per-file metrics. Files that are not graph nodes get NULL metrics."""
    kinds: dict[tuple[str, str], set[str]] = {}
    for e in edges:
        if e.source != e.target:
            kinds.setdefault((e.source, e.target), set()).add(e.kind)

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dependencies WHERE repo_id = %s", (repo_id,))
            cur.execute("DELETE FROM dependency_cycles WHERE repo_id = %s", (repo_id,))
            cur.execute("DELETE FROM module_edges WHERE repo_id = %s", (repo_id,))
            cur.execute("UPDATE files SET module=NULL, fan_in=NULL, fan_out=NULL, pagerank=NULL, "
                        "cycle_idx=NULL WHERE repo_id = %s", (repo_id,))
            cur.executemany(
                "UPDATE files SET module=%s, fan_in=%s, fan_out=%s, pagerank=%s, cycle_idx=%s WHERE id=%s",
                [(analysis.modules[p], analysis.fan[p][0], analysis.fan[p][1], analysis.pagerank[p],
                  analysis.cycle_of.get(p), file_ids[p]) for p in analysis.graph.nodes],
            )
            cur.executemany(
                "INSERT INTO dependencies (repo_id, from_file_id, to_file_id, kinds) VALUES (%s,%s,%s,%s)",
                [(repo_id, file_ids[a], file_ids[b], Jsonb(sorted(k))) for (a, b), k in sorted(kinds.items())
                 if b in analysis.graph.successors[a]],
            )
            cur.executemany(
                "INSERT INTO dependency_cycles (repo_id, cycle_idx, size, file_ids) VALUES (%s,%s,%s,%s)",
                [(repo_id, i, len(group), Jsonb([file_ids[p] for p in group]))
                 for i, group in enumerate(analysis.cycles)],
            )
            rows = [(repo_id, a, b, n) for (a, b), n in analysis.cross_module_edges.items()]
            rows += [(repo_id, m, m, n) for m, n in analysis.internal_module_edges.items()]
            cur.executemany(
                "INSERT INTO module_edges (repo_id, from_module, to_module, edge_count) VALUES (%s,%s,%s,%s)",
                rows,
            )


def save_git_stats(conn: psycopg.Connection, repo_id: int, job_id: int, file_ids: dict[str, int], stats) -> None:
    """Churn/authors/last-modified per file + co-change pairs. Without usable history the columns
    are NULL (unknown), never 0 (which would claim "stable")."""
    history = stats.commits_seen > 0
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("UPDATE files SET churn=NULL, commits_total=NULL, authors=NULL, last_modified=NULL "
                        "WHERE repo_id=%s", (repo_id,))
            if history:
                rows = []
                for path, fid in file_ids.items():
                    g = stats.files.get(path)
                    rows.append((g.commits_window if g else 0, g.commits_total if g else 0,
                                 g.authors if g else 0, g.last_modified if g else None, fid))
                cur.executemany("UPDATE files SET churn=%s, commits_total=%s, authors=%s, last_modified=%s "
                                "WHERE id=%s", rows)
            cur.execute("DELETE FROM file_cochange WHERE repo_id=%s", (repo_id,))
            cur.executemany(
                "INSERT INTO file_cochange (repo_id, file_a_id, file_b_id, count, coupling) VALUES (%s,%s,%s,%s,%s)",
                [(repo_id, file_ids[c.file_a], file_ids[c.file_b], c.count, c.coupling)
                 for c in stats.cochange if c.file_a in file_ids and c.file_b in file_ids])
            cur.execute("UPDATE analysis_jobs SET history_commits=%s, history_window_days=%s, history_truncated=%s "
                        "WHERE id=%s", (stats.commits_seen, stats.window_days, stats.truncated, job_id))


def save_duplicates(conn: psycopg.Connection, repo_id: int, file_ids: dict[str, int],
                    file_lines: dict[str, int], dups) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM duplicate_groups WHERE repo_id=%s", (repo_id,))  # cascades to blocks
            cur.execute("UPDATE files SET dup_lines=NULL, dup_ratio=NULL WHERE repo_id=%s", (repo_id,))
            cur.executemany(
                "UPDATE files SET dup_lines=%s, dup_ratio=%s WHERE id=%s",
                [(dups.duplicated_lines.get(p, 0), min(1.0, dups.duplicated_lines.get(p, 0) / max(n, 1)), file_ids[p])
                 for p, n in file_lines.items() if p in file_ids])
            for idx, g in enumerate(dups.groups):
                cur.execute("INSERT INTO duplicate_groups (repo_id, idx, lines, tokens, total_locations) "
                            "VALUES (%s,%s,%s,%s,%s)", (repo_id, idx, g.lines, g.tokens, g.total_locations))
                cur.executemany(
                    "INSERT INTO duplicate_blocks (repo_id, group_idx, file_id, start_line, end_line) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    [(repo_id, idx, file_ids[loc.path], loc.start_line, loc.end_line) for loc in g.locations])


def save_hotspots(conn: psycopg.Connection, repo_id: int, job_id: int, file_ids: dict[str, int],
                  scored, config) -> None:
    """scored = [(HotspotInputs, HotspotScore | None, [Reason])]. Score columns stay NULL while the
    formula is unimplemented; has_test/test_file are saved either way."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("UPDATE files SET hotspot_score=NULL, hotspot_reasons='[]', hotspot_detail=NULL, "
                        "has_test=NULL, test_file=NULL WHERE repo_id=%s", (repo_id,))
            cur.executemany(
                """UPDATE files SET has_test=%s, test_file=%s, hotspot_score=%s, hotspot_reasons=%s,
                          hotspot_detail=%s WHERE id=%s""",
                [(i.has_test, i.test_file, s.score if s else None, Jsonb([r.to_dict() for r in reasons]),
                  Jsonb({"contributions": s.contributions, "normalized": s.normalized}) if s else None,
                  file_ids[i.path]) for i, s, reasons in scored])
            cur.execute("UPDATE analysis_jobs SET hotspot_config=%s WHERE id=%s", (Jsonb(config.to_dict()), job_id))


def save_chunks(conn: psycopg.Connection, repo_id: int, file_ids: dict[str, int], chunks) -> None:
    """Replace a repo's chunks (keyword-searchable immediately; vectors are attached afterwards)."""
    import hashlib
    counters: dict[tuple[str, str], int] = {}
    rows = []
    for c in chunks:
        key = (c.path, c.strategy)
        idx = counters[key] = counters.get(key, -1) + 1
        rows.append((repo_id, file_ids[c.path], c.strategy, idx, c.path, c.language, c.kind, c.symbol, c.parent,
                     c.start_line, c.end_line, c.header, c.content,
                     hashlib.sha256(c.content.encode("utf8", errors="replace")).hexdigest(), c.embed_hash,
                     expand_identifiers(c.embed_text)))
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE repo_id = %s", (repo_id,))
            cur.executemany(
                """INSERT INTO chunks (repo_id, file_id, strategy, idx, path, language, kind, symbol, parent_name,
                                       start_line, end_line, header, content, content_hash, embed_hash, tsv)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, to_tsvector('simple', %s))""", rows)


def apply_cached_embeddings(conn: psycopg.Connection, repo_id: int, model: str, strategies: tuple[str, ...]) -> int:
    """Give every un-embedded chunk whose text was embedded before its vector, in one statement."""
    return conn.execute(
        """UPDATE chunks c SET embedding = e.embedding, embed_model = e.model
           FROM embedding_cache e
           WHERE c.repo_id = %s AND c.embedding IS NULL AND c.strategy = ANY(%s)
             AND e.embed_hash = c.embed_hash AND e.model = %s""",
        (repo_id, list(strategies), model)).rowcount


def pending_embeddings(conn: psycopg.Connection, repo_id: int, limit: int,
                       strategies: tuple[str, ...]) -> list[tuple[str, str]]:
    """Distinct texts still without a vector: [(embed_hash, header+content)]."""
    return [(h, f"{head}\n{body}") for h, head, body in conn.execute(
        """SELECT DISTINCT ON (embed_hash) embed_hash, header, content FROM chunks
           WHERE repo_id = %s AND embedding IS NULL AND strategy = ANY(%s) ORDER BY embed_hash LIMIT %s""",
        (repo_id, list(strategies), limit))]


def count_pending(conn: psycopg.Connection, repo_id: int, strategies: tuple[str, ...]) -> int:
    return conn.execute("SELECT count(DISTINCT embed_hash) FROM chunks "
                        "WHERE repo_id=%s AND embedding IS NULL AND strategy = ANY(%s)",
                        (repo_id, list(strategies))).fetchone()[0]


def store_embeddings(conn: psycopg.Connection, repo_id: int, model: str, items: list[tuple[str, str]]) -> None:
    """items = [(embed_hash, pgvector literal)]: write to the cache and to every chunk with that text."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO embedding_cache (embed_hash, model, embedding) VALUES (%s,%s,%s::vector) "
                            "ON CONFLICT DO NOTHING", [(h, model, v) for h, v in items])
            cur.executemany("UPDATE chunks SET embedding=%s::vector, embed_model=%s "
                            "WHERE repo_id=%s AND embed_hash=%s AND embedding IS NULL",
                            [(v, model, repo_id, h) for h, v in items])


def save_index_stats(conn: psycopg.Connection, job_id: int, stats) -> None:
    conn.execute("""UPDATE analysis_jobs SET chunks_total=%s, chunks_embedded=%s, chunks_cached=%s,
                    embed_model=%s, index_partial=%s WHERE id=%s""",
                 (stats.chunks_total, stats.embedded, stats.cached, stats.model, stats.partial, job_id))
