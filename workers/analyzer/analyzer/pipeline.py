import logging
import shutil
from pathlib import Path

from . import config, db
from .clone import CloneError, clone
from .inventory import InventoryError, build_inventory
from .graph.edges import edges_from_resolutions
from .graph.metrics import analyze
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
                db.update_progress(conn, r, job_id, "parsing", 50 + int(40 * n / len(targets)))
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


def run_job(conn, r, job_id: int) -> None:
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
        sha = clone(url, dest)

        db.update_progress(conn, r, job_id, "inventory", 30, commit_sha=sha)
        records = build_inventory(dest)

        db.update_progress(conn, r, job_id, "saving", 45, commit_sha=sha)
        file_ids = db.save_files(conn, repo_id, sha, records)

        db.update_progress(conn, r, job_id, "parsing", 50, commit_sha=sha)
        results = parse_files(conn, r, job_id, dest, file_ids, records)
        db.save_parse_results(conn, repo_id, results)

        db.update_progress(conn, r, job_id, "resolving", 92, commit_sha=sha)
        resolutions = resolve_all(dest, file_ids, results)
        db.save_resolutions(conn, repo_id, file_ids, resolutions)
        counts = summarize(resolutions)

        db.update_progress(conn, r, job_id, "graph", 96, commit_sha=sha)
        code_files = {f.path for f in records if supported(f.path)}
        edges = edges_from_resolutions(resolutions, code_files)
        analysis = analyze(sorted(code_files), edges)
        db.save_graph(conn, repo_id, file_ids, analysis, edges)

        db.set_repo_status(conn, repo_id, "ready", sha)
        db.update_progress(conn, r, job_id, "done", 100, "done", commit_sha=sha)
        bad = sum(1 for x in results.values() if x.status in ("failed", "partial"))
        log.info("job %s done: %d files (%d parsed, %d with problems); imports %s; graph %d nodes, %d cycles @ %s",
                 job_id, len(records), len(results), bad, counts,
                 len(analysis.graph.nodes), len(analysis.cycles), sha[:8])
    except (CloneError, InventoryError) as e:
        # Permanent, user-facing failure: don't retry.
        log.warning("job %s failed: %s", job_id, e)
        db.update_progress(conn, r, job_id, "failed", 0, "failed", str(e))
        db.set_repo_status(conn, repo_id, "failed")
    finally:
        shutil.rmtree(dest, ignore_errors=True)
