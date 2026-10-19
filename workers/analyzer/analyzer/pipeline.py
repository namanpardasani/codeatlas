import logging
import shutil
from pathlib import Path

from . import config, db
from .clone import CloneError, LimitError, clone
from .inventory import InventoryError, build_inventory
from . import gitstats
from .duplication import find_duplicates
from .graph.edges import edges_from_resolutions
from .graph.metrics import analyze
from .chunking import is_indexable
from .hotspots import HotspotConfig, RepoContext, map_tests, score_all, score_file
from .hotspots.inputs import build_inputs
from .indexing import SourceFile, index_repo
from .parsing import supported
from .parsing.runner import SandboxedParser
from .parsing.types import ParseResult
from .resolve import resolve_imports, summarize
from .resolve.types import ImportItem

log = logging.getLogger("analyzer.pipeline")


def parse_files(conn, r, job_id: int, root: Path, file_ids: dict[str, int],
                records) -> dict[int, ParseResult]:
    """Parse every supported file; one bad file never fails the job."""
    targets = [f for f in records if supported(f.path)]
    results: dict[int, ParseResult] = {}
    step = max(1, len(targets) // 20)
    root = root.resolve()
    with SandboxedParser() as parser:
        for n, f in enumerate(targets, 1):
            fid = file_ids[f.path]
            full = (root / f.path).resolve()
            if not full.is_relative_to(root):  # inventory never yields these; belt and braces
                results[fid] = ParseResult(status="failed", error="path escapes repo")
                continue
            try:
                source = full.read_bytes()
            except OSError as e:
                results[fid] = ParseResult(status="failed", error=f"read error: {e}"[:300])
                continue
            results[fid] = parser.parse(f.path, source)
            if n % step == 0:
                db.update_progress(conn, r, job_id, "parsing", 50 + int(28 * n / len(targets)))
    return results


def resolve_all(root: Path, file_ids: dict[str, int], results: dict[int, ParseResult]):
    """Resolve every parsed import against the set of analysed files."""
    root = root.resolve()
    id_to_path = {fid: p for p, fid in file_ids.items()}

    def read_text(path: str) -> str | None:  # tsconfig / package.json contents
        full = (root / path).resolve()
        if not full.is_relative_to(root):
            return None
        try:
            return full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    items = [
        ImportItem(id_to_path[fid], i, im.specifier, im.kind, im.names, im.level)
        for fid, res in results.items() for i, im in enumerate(res.imports)
    ]
    return resolve_imports(set(file_ids), items, read_text)


def load_sources(root: Path, records, by_path: dict) -> list[SourceFile]:
    """Text + symbols of every indexable file (docs/config/code), read safely from the clone."""
    root = root.resolve()
    out: list[SourceFile] = []
    for rec in records:
        if not is_indexable(rec.path, rec.language, rec.size):
            continue
        full = (root / rec.path).resolve()
        if not full.is_relative_to(root):
            continue
        try:
            text = full.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        res = by_path.get(rec.path)
        out.append(SourceFile(rec.path, rec.language, rec.size, text, res.symbols if res else []))
    return out


def run_job(conn, r, job_id: int, embedders=None) -> None:
    """Run one analysis job. Idempotent: safe to run again after a crash."""
    job = db.get_job(conn, job_id)
    if job is None:
        log.warning("job %s not found, dropping", job_id)
        return
    _id, repo_id, status, _attempts, url = job
    if status == "done":
        return

    attempts = db.start_job(conn, job_id)
    if attempts > config.MAX_ATTEMPTS:
        db.update_progress(conn, r, job_id, "failed", 0, "failed", "too many attempts")
        db.set_repo_status(conn, repo_id, "failed")
        return

    dest = Path(config.WORK_DIR) / f"job-{job_id}"
    try:
        db.set_repo_status(conn, repo_id, "analyzing")
        db.update_progress(conn, r, job_id, "cloning", 5)
        try:
            sha = clone(url, dest)  # bounded history (for churn)
        except LimitError as e:
            log.warning("job %s: history clone hit a limit (%s); retrying with HEAD only", job_id, e)
            sha = clone(url, dest, history=False)

        db.update_progress(conn, r, job_id, "inventory", 30, commit_sha=sha)
        records = build_inventory(dest)

        db.update_progress(conn, r, job_id, "saving", 45, commit_sha=sha)
        file_ids = db.save_files(conn, repo_id, sha, records)

        db.update_progress(conn, r, job_id, "parsing", 50, commit_sha=sha)
        results = parse_files(conn, r, job_id, dest, file_ids, records)
        db.save_parse_results(conn, repo_id, results)

        db.update_progress(conn, r, job_id, "resolving", 80, commit_sha=sha)
        resolutions = resolve_all(dest, file_ids, results)
        db.save_resolutions(conn, repo_id, file_ids, resolutions)
        counts = summarize(resolutions)

        db.update_progress(conn, r, job_id, "graph", 82, commit_sha=sha)
        code_files = {f.path for f in records if supported(f.path)}
        edges = edges_from_resolutions(resolutions, code_files)
        analysis = analyze(sorted(code_files), edges)
        db.save_graph(conn, repo_id, file_ids, analysis, edges)

        db.update_progress(conn, r, job_id, "git history", 84, commit_sha=sha)
        git = gitstats.collect(dest, tracked=set(file_ids))
        db.save_git_stats(conn, repo_id, job_id, file_ids, git)

        db.update_progress(conn, r, job_id, "duplication", 86, commit_sha=sha)
        path_of = {fid: p for p, fid in file_ids.items()}
        by_path = {path_of[fid]: res for fid, res in results.items()}
        dups = find_duplicates({p: (x.token_hashes, x.token_lines) for p, x in by_path.items()})
        db.save_duplicates(conn, repo_id, file_ids, {p: (x.metrics.lines if x.metrics else 0) for p, x in by_path.items()}, dups)

        db.update_progress(conn, r, job_id, "hotspots", 88, commit_sha=sha)
        tests = map_tests([f.path for f in records if f.path in by_path and not f.is_test],
                          [f.path for f in records if f.is_test])
        hs_inputs = build_inputs(records, by_path, analysis, git, dups, tests)
        hs_config = HotspotConfig.from_env()
        hs_ctx = RepoContext.build(hs_inputs, history_available=git.commits_seen > 0, window_days=git.window_days)
        scored = score_all(hs_inputs, hs_ctx, hs_config, score_file)
        db.save_hotspots(conn, repo_id, job_id, file_ids, scored, hs_config)
        if scored and scored[0][1] is None:
            log.info("job %s: hotspot formula not implemented yet; scores left empty", job_id)

        db.update_progress(conn, r, job_id, "chunking", 90, commit_sha=sha)
        sources = load_sources(dest, records, by_path)
        db.save_file_contents(conn, repo_id, file_ids, sources)
        embedder = embedders.get() if embedders else None
        index = index_repo(conn, embedder, repo_id, file_ids, sources,
                           on_progress=lambda f: db.update_progress(conn, r, job_id, "embedding", 91 + int(8 * f),
                                                                    commit_sha=sha))
        db.save_index_stats(conn, job_id, index)
        if index.partial:
            log.warning("job %s: index partial (model=%s, truncated=%s)", job_id, index.model, index.truncated)

        db.set_repo_status(conn, repo_id, "ready", sha)
        db.update_progress(conn, r, job_id, "done", 100, "done", commit_sha=sha)
        bad = sum(1 for x in results.values() if x.status in ("failed", "partial"))
        log.info("job %s done: %d files (%d parsed, %d with problems); imports %s; graph %d nodes, %d cycles; history %d commits%s; %d duplicate groups; %d chunks (%d embedded, %d cached) @ %s",
                 job_id, len(records), len(results), bad, counts,
                 len(analysis.graph.nodes), len(analysis.cycles), git.commits_seen,
                 " (truncated)" if git.truncated else "", len(dups.groups),
                 index.chunks_total, index.embedded, index.cached, sha[:8])
    except (CloneError, InventoryError) as e:
        # Permanent, user-facing failure: don't retry.
        log.warning("job %s failed: %s", job_id, e)
        db.update_progress(conn, r, job_id, "failed", 0, "failed", str(e))
        db.set_repo_status(conn, repo_id, "failed")
    finally:
        shutil.rmtree(dest, ignore_errors=True)
