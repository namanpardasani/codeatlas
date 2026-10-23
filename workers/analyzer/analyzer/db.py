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


def apply_renames(cur, repo_id: int, renames: list[tuple[str, str]]) -> None:
    """Move rows to their new path, keeping their ids. Two phases through unique placeholders so that swaps and
    chains (a->b, b->c) cannot violate UNIQUE (repo_id, path) half-way."""
    for i, (old, _) in enumerate(renames):
        cur.execute("UPDATE files SET path = %s WHERE repo_id = %s AND path = %s", (f"__rename__{i}__", repo_id, old))
    for i, (_, new) in enumerate(renames):
        cur.execute("UPDATE files SET path = %s WHERE repo_id = %s AND path = %s", (new, repo_id, f"__rename__{i}__"))


def save_files(conn: psycopg.Connection, repo_id: int, commit_sha: str,
               records: list[FileRecord], renames: list[tuple[str, str]] | None = None) -> dict[str, int]:
    """Idempotent: (renames), upsert on (repo_id, path), then drop files that no longer exist."""
    with conn.transaction():
        with conn.cursor() as cur:
            if renames:
                apply_renames(cur, repo_id, renames)
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
                       results: dict[int, ParseResult], replace_all: bool = True) -> None:
    """Replace parse output atomically: the whole repo's (replace_all) or only the given files' (incremental).
    Idempotent: re-running yields identical rows, never duplicates (delete-then-insert + UNIQUE (file_id, idx))."""
    with conn.transaction():
        with conn.cursor() as cur:
            if replace_all:
                cur.execute("DELETE FROM symbols WHERE repo_id = %s", (repo_id,))
                cur.execute("DELETE FROM imports_raw WHERE repo_id = %s", (repo_id,))
            else:
                ids = list(results)
                cur.execute("DELETE FROM symbols WHERE repo_id = %s AND file_id = ANY(%s)", (repo_id, ids))
                cur.execute("DELETE FROM imports_raw WHERE repo_id = %s AND file_id = ANY(%s)", (repo_id, ids))
            cur.executemany(
                """UPDATE files SET parse_status=%s, parse_error=%s, exports=%s, export_aliases=%s,
                          code_lines=%s, comment_lines=%s, comment_ratio=%s, total_complexity=%s,
                          max_complexity=%s, max_nesting=%s, function_count=%s, longest_function=%s
                   WHERE id=%s""",
                [(r.status, r.error, Jsonb(r.exports), Jsonb([list(a) for a in r.export_aliases]),
                  r.metrics.code_lines if r.metrics else None, r.metrics.comment_lines if r.metrics else None,
                  r.metrics.comment_ratio if r.metrics else None,
                  *((a["total_complexity"], a["max_complexity"], a["max_nesting"], a["function_count"],
                     a["longest_function"]) if r.metrics else (None,) * 5),
                  fid) for fid, r in ((fid, r) for fid, r in results.items()) for a in [file_aggregates(r)]],
            )
            cur.executemany(
                """INSERT INTO symbols (repo_id, file_id, idx, name, kind, start_line, end_line, params,
                                        parent_name, is_exported, is_default_export, has_doc, signature,
                                        complexity, max_nesting, param_count, body_hash, bases)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(repo_id, fid, i, s.name, s.kind, s.start_line, s.end_line, Jsonb(s.params),
                  s.parent, s.is_exported, s.is_default_export, s.has_doc, s.signature,
                  s.complexity, s.max_nesting if s.complexity is not None else None, s.param_count, s.body_hash, Jsonb(s.bases))
                 for fid, r in results.items() for i, s in enumerate(r.symbols)],
            )
            cur.executemany(
                """INSERT INTO imports_raw (repo_id, file_id, idx, specifier, kind, names, level, line, is_type_only, bindings)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(repo_id, fid, i, im.specifier, im.kind, Jsonb(im.names), im.level, im.line, im.is_type_only,
                  Jsonb([list(b) for b in im.bindings]))
                 for fid, r in results.items() for i, im in enumerate(r.imports)],
            )
            cur.execute("DELETE FROM file_call_sites WHERE file_id = ANY(%s)", (list(results),))
            cur.executemany(
                "INSERT INTO file_call_sites (file_id, repo_id, calls, var_types) VALUES (%s,%s,%s,%s)",
                [(fid, repo_id, Jsonb([[c.callee, c.qualifier, c.line, c.kind] for c in r.calls]),
                  Jsonb([[v.name, v.type_name, v.line] for v in r.var_types]))
                 for fid, r in results.items() if r.status in ("ok", "partial")],
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


def save_cochange_rules(conn: psycopg.Connection, repo_id: int, job_id: int, file_ids: dict[str, int], model) -> None:
    """Directional co-change rules (analyzer/blast/cochange.py). Replaced wholesale: they are cheap to recompute."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cochange_rules WHERE repo_id=%s", (repo_id,))
            cur.executemany(
                """INSERT INTO cochange_rules (repo_id, source_file_id, target_file_id, support, confidence)
                   VALUES (%s,%s,%s,%s,%s)""",
                [(repo_id, file_ids[r.source], file_ids[r.target], r.support, r.confidence)
                 for rules in model.rules.values() for r in rules if r.source in file_ids and r.target in file_ids])
            cur.execute("UPDATE analysis_jobs SET cochange_commits_used=%s, cochange_commits_skipped=%s WHERE id=%s",
                        (model.commits_used, model.commits_skipped_large, job_id))


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


def save_chunks(conn: psycopg.Connection, repo_id: int, file_ids: dict[str, int], chunks,
                only_file_ids: set[int] | None = None) -> None:
    """Replace a repo's chunks, or only those of `only_file_ids` (incremental). Keyword-searchable immediately;
    vectors are attached afterwards."""
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
            if only_file_ids is None:
                cur.execute("DELETE FROM chunks WHERE repo_id = %s", (repo_id,))
            else:
                cur.execute("DELETE FROM chunks WHERE repo_id = %s AND file_id = ANY(%s)", (repo_id, list(only_file_ids)))
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
    """Distinct texts still without a vector: [(embed_hash, header+content)]. Source and docs come before
    test files, so if the time budget cuts embedding short the most valuable chunks already have vectors."""
    return [(h, f"{head}\n{body}") for h, head, body in conn.execute(
        r"""SELECT embed_hash, header, content FROM (
              SELECT DISTINCT ON (embed_hash) embed_hash, header, content,
                     (path ~* '(^|/)(tests?|__tests__|specs?)/' OR path ~* '(^|/)test_[^/]*$'
                      OR path ~* '[._](test|spec)\.[a-z]+$') AS is_test
              FROM chunks WHERE repo_id = %s AND embedding IS NULL AND strategy = ANY(%s)
              ORDER BY embed_hash, is_test) t
            ORDER BY is_test, embed_hash LIMIT %s""",
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


def save_file_contents(conn: psycopg.Connection, repo_id: int, file_ids: dict[str, int], sources,
                       replace_all: bool = True, refresh_paths: set[str] | None = None) -> None:
    """Keep the text of indexable files so the UI can open a citation at its lines (the clone is deleted).
    Incremental: only `refresh_paths` are rewritten (and removed when they stopped being indexable)."""
    rows = [(file_ids[f.path], f.text) for f in sources if f.path in file_ids]
    with conn.transaction():
        with conn.cursor() as cur:
            if replace_all:
                cur.execute("DELETE FROM file_contents WHERE file_id IN (SELECT id FROM files WHERE repo_id = %s)", (repo_id,))
            elif refresh_paths:
                cur.execute("DELETE FROM file_contents WHERE file_id = ANY(%s)",
                            ([file_ids[p] for p in refresh_paths if p in file_ids],))
            cur.executemany("INSERT INTO file_contents (file_id, content) VALUES (%s, %s) ON CONFLICT (file_id) DO UPDATE "
                            "SET content = EXCLUDED.content", rows)


# ---- incremental re-analysis: what the previous run left behind -------------------------------------------
def load_file_state(conn: psycopg.Connection, repo_id: int) -> dict[str, tuple[int, str]]:
    """path -> (file id, content hash) as of the previous analysis."""
    return {path: (fid, h) for fid, path, h in conn.execute(
        "SELECT id, path, content_hash FROM files WHERE repo_id = %s", (repo_id,)).fetchall()}


def load_repo_state(conn: psycopg.Connection, repo_id: int):
    """(status, pipeline_version, last_commit_sha) of the repo."""
    return conn.execute("SELECT status, pipeline_version, last_commit_sha FROM repos WHERE id = %s", (repo_id,)).fetchone()


def set_pipeline_version(conn: psycopg.Connection, repo_id: int, version: int) -> None:
    conn.execute("UPDATE repos SET pipeline_version = %s WHERE id = %s", (version, repo_id))


def save_tokens(conn: psycopg.Connection, results: dict[int, ParseResult]) -> None:
    """Persist each parsed file's normalised token stream (packed uint32), so unchanged files need no re-parse."""
    import array
    rows = []
    for fid, r in results.items():
        if r.token_hashes:
            rows.append((fid, len(r.token_hashes), array.array("I", r.token_hashes).tobytes(),
                         array.array("I", r.token_lines).tobytes()))
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM file_tokens WHERE file_id = ANY(%s)", (list(results),))
            cur.executemany("INSERT INTO file_tokens (file_id, n, hashes, lines) VALUES (%s,%s,%s,%s)", rows)


def load_tokens(conn: psycopg.Connection, repo_id: int, exclude_file_ids: set[int]) -> dict[str, tuple[list[int], list[int]]]:
    import array
    out = {}
    for path, n, hashes, lines in conn.execute(
            """SELECT f.path, t.n, t.hashes, t.lines FROM file_tokens t JOIN files f ON f.id = t.file_id
               WHERE f.repo_id = %s AND NOT (f.id = ANY(%s))""", (repo_id, list(exclude_file_ids))):
        h, ln = array.array("I"), array.array("I")
        h.frombytes(bytes(hashes))
        ln.frombytes(bytes(lines))
        out[path] = (h.tolist(), ln.tolist())
    return out


def load_import_items(conn: psycopg.Connection, repo_id: int, exclude_file_ids: set[int]):
    """Raw imports of files that were NOT re-parsed, as resolver input."""
    from .resolve.types import ImportItem
    return [ImportItem(path, idx, spec, kind, list(names), level) for path, idx, spec, kind, names, level in conn.execute(
        """SELECT f.path, i.idx, i.specifier, i.kind, i.names, i.level FROM imports_raw i JOIN files f ON f.id = i.file_id
           WHERE i.repo_id = %s AND NOT (i.file_id = ANY(%s)) ORDER BY f.path, i.idx""", (repo_id, list(exclude_file_ids)))]


def load_parse_summaries(conn: psycopg.Connection, repo_id: int, file_ids: list[int]) -> dict[str, ParseResult]:
    """Rebuild ParseResults (symbols + line metrics; no tokens/imports) for files that were NOT re-parsed, so the
    hotspot and duplication stages see every file."""
    from .parsing.types import FileMetrics, Symbol
    out: dict[str, ParseResult] = {}
    by_id: dict[int, ParseResult] = {}
    for fid, path, status, error, exports, lines, code, comment, ratio in conn.execute(
            """SELECT id, path, parse_status, parse_error, exports, lines, code_lines, comment_lines, comment_ratio
               FROM files WHERE repo_id = %s AND id = ANY(%s) AND parse_status IS NOT NULL""", (repo_id, file_ids)):
        metrics = None if code is None else FileMetrics(lines=lines, blank_lines=max(0, lines - code - (comment or 0)),
                                                        comment_lines=comment or 0, code_lines=code, comment_ratio=ratio or 0.0)
        res = ParseResult(status=status, error=error, exports=list(exports or []), metrics=metrics)
        by_id[fid] = res
        out[path] = res
    for (fid, name, kind, start, end, params, parent, exported, default, doc, signature, cx, nest, pcount, bh, bases) in conn.execute(
            """SELECT file_id, name, kind, start_line, end_line, params, parent_name, is_exported, is_default_export,
                      has_doc, signature, complexity, max_nesting, param_count, body_hash, bases
               FROM symbols WHERE repo_id = %s AND file_id = ANY(%s) ORDER BY file_id, idx""", (repo_id, file_ids)):
        by_id[fid].symbols.append(Symbol(name, kind, start, end, list(params or []), parent, exported, default, doc,
                                         signature, cx, nest or 0, pcount or 0, bh or "", list(bases or [])))
    return out


def save_job_stats(conn: psycopg.Connection, job_id: int, *, mode: str, diff: dict, files_total: int, files_reused: int,
                   timings: dict, duration_ms: int) -> None:
    conn.execute(
        """UPDATE analysis_jobs SET mode=%s, files_total=%s, files_added=%s, files_modified=%s, files_deleted=%s,
                  files_renamed=%s, files_reused=%s, stage_timings=%s, duration_ms=%s WHERE id=%s""",
        (mode, files_total, diff.get("added", 0), diff.get("modified", 0), diff.get("deleted", 0), diff.get("renamed", 0),
         files_reused, Jsonb(timings), duration_ms, job_id))


def get_requested_mode(conn: psycopg.Connection, job_id: int) -> str:
    row = conn.execute("SELECT requested_mode FROM analysis_jobs WHERE id = %s", (job_id,)).fetchone()
    return row[0] if row else "auto"


def save_repo_facts(conn: psycopg.Connection, repo_id: int, facts: dict) -> None:
    conn.execute("""INSERT INTO repo_facts (repo_id, facts, updated_at) VALUES (%s, %s, now())
                    ON CONFLICT (repo_id) DO UPDATE SET facts = EXCLUDED.facts, updated_at = now()""", (repo_id, Jsonb(facts)))


def set_docs_status(conn: psycopg.Connection, repo_id: int, status: str) -> None:
    conn.execute("UPDATE repos SET docs_status = %s WHERE id = %s", (status, repo_id))


def save_docs_stats(conn: psycopg.Connection, job_id: int, stats) -> None:
    conn.execute("UPDATE analysis_jobs SET docs_llm_calls=%s, docs_cached=%s, docs_extractive=%s WHERE id=%s",
                 (stats.llm_calls, stats.cached + stats.reused, stats.extractive, job_id))


def load_call_inputs(conn: psycopg.Connection, repo_id: int, summaries: dict[str, ParseResult]) -> None:
    """Complete reused files' ParseResults with what call resolution needs (imports + bindings, call sites, type hints,
    export aliases), so an incremental run rebuilds the repo-wide call graph without re-parsing unchanged files."""
    from .parsing.types import CallSite, RawImport, VarType
    if not summaries:
        return
    rows = conn.execute("SELECT id, path, export_aliases FROM files WHERE repo_id = %s AND path = ANY(%s)",
                        (repo_id, list(summaries))).fetchall()
    by_id = {fid: summaries[path] for fid, path, _ in rows}
    for fid, path, aliases in rows:
        summaries[path].export_aliases = [tuple(a) for a in (aliases or [])]
        summaries[path].imports = []
    for fid, spec, kind, names, level, line, type_only, bindings in conn.execute(
            """SELECT file_id, specifier, kind, names, level, line, is_type_only, bindings FROM imports_raw
               WHERE repo_id = %s AND file_id = ANY(%s) ORDER BY file_id, idx""", (repo_id, list(by_id))):
        by_id[fid].imports.append(RawImport(spec, kind, line, list(names or []), level, type_only,
                                            [tuple(b) for b in (bindings or [])]))
    for fid, calls, var_types in conn.execute(
            "SELECT file_id, calls, var_types FROM file_call_sites WHERE repo_id = %s AND file_id = ANY(%s)",
            (repo_id, list(by_id))):
        by_id[fid].calls = [CallSite(c[0], c[1], c[2], c[3]) for c in calls]
        by_id[fid].var_types = [VarType(v[0], v[1], v[2]) for v in var_types]


def save_call_graph(conn: psycopg.Connection, repo_id: int, job_id: int, file_ids: dict[str, int], graph) -> None:
    """Replace the repo's call edges and unresolved calls. Symbols are addressed by (file, idx) in the graph and mapped
    to row ids here."""
    sym_id = {(fid, idx): sid for sid, fid, idx in conn.execute(
        "SELECT id, file_id, idx FROM symbols WHERE repo_id = %s", (repo_id,))}

    def sid(ref):
        return None if ref is None else sym_id.get((file_ids[ref.path], ref.idx))

    edges = []
    for e in graph.edges:
        if e.caller_path not in file_ids or e.callee.path not in file_ids:
            continue
        callee = sid(e.callee)
        if callee is None:
            continue
        edges.append((repo_id, file_ids[e.caller_path], sid(e.caller), file_ids[e.callee.path], callee,
                      e.confidence, e.line, e.kind, e.via))
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("DELETE FROM call_edges WHERE repo_id = %s", (repo_id,))
            cur.execute("DELETE FROM unresolved_calls WHERE repo_id = %s", (repo_id,))
            cur.executemany(
                """INSERT INTO call_edges (repo_id, caller_file_id, caller_symbol_id, callee_file_id, callee_symbol_id,
                                           confidence, line, kind, via) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", edges)
            cur.executemany(
                """INSERT INTO unresolved_calls (repo_id, file_id, caller_symbol_id, callee, qualifier, line, reason)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                [(repo_id, file_ids[u.path], sid(u.caller), u.callee, u.qualifier, u.line, u.reason)
                 for u in graph.unresolved if u.path in file_ids])
            cur.execute("UPDATE analysis_jobs SET call_stats = %s WHERE id = %s", (Jsonb(dict(graph.stats)), job_id))
