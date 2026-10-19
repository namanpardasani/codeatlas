import logging
import shutil
from pathlib import Path

from . import config, db
from .analysis import analyze_checkout
from .clone import CloneError, LimitError, clone
from .docs.generate import generate_docs
from .llm import LLMError, get_llm
from .inventory import InventoryError

log = logging.getLogger("analyzer.pipeline")


def run_docs(conn, repo_id: int, job_id: int, sha: str) -> None:
    """Documentation runs AFTER the analysis is marked done: search/chat/graph are usable meanwhile, and a slow or
    unavailable LLM can only delay the docs, never fail the job."""
    if not config.DOCS_ENABLED:
        return
    try:
        db.set_docs_status(conn, repo_id, "running")
        try:
            llm = get_llm()
        except LLMError as e:
            log.info("docs: no usable LLM (%s); extractive summaries only", e.message)
            llm = None
        stats = generate_docs(conn, llm, repo_id, sha)
        db.save_docs_stats(conn, job_id, stats)
        log.info("docs for repo %s: %d targets, %d LLM calls (budget %d%s), %d reused, %d cached, %d extractive%s",
                 repo_id, stats.targets, stats.llm_calls, stats.budget, ", exhausted" if stats.budget_exhausted else "",
                 stats.reused, stats.cached, stats.extractive,
                 f"; LLM stopped: {stats.llm_disabled_reason}" if stats.llm_disabled_reason else "")
    except Exception:  # noqa: BLE001  docs must never fail an analysis that already succeeded
        log.exception("docs generation failed for repo %s", repo_id)
        db.set_docs_status(conn, repo_id, "failed")


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
    # one analysis per repo at a time (two jobs for the same repo would interleave their writes)
    conn.execute("SELECT pg_advisory_lock(%s)", (repo_id,))
    try:
        repo_status, repo_version, _last_sha = db.load_repo_state(conn, repo_id)  # BEFORE we mark it analyzing
        requested = db.get_requested_mode(conn, job_id)
        db.set_repo_status(conn, repo_id, "analyzing")
        db.update_progress(conn, r, job_id, "cloning", 5)
        try:
            sha = clone(url, dest)  # bounded history (for churn)
        except LimitError as e:
            log.warning("job %s: history clone hit a limit (%s); retrying with HEAD only", job_id, e)
            sha = clone(url, dest, history=False)

        def progress(stage: str, pct: int) -> None:
            db.update_progress(conn, r, job_id, stage, pct, commit_sha=sha)

        result = analyze_checkout(
            conn, repo_id, job_id, dest, sha, progress=progress, embedder=embedders.get() if embedders else None,
            requested_mode=requested, previous_ready=repo_status == "ready", previous_version=repo_version)
        db.save_job_stats(conn, job_id, mode=result.mode, diff=result.diff, files_total=result.files_total,
                          files_reused=result.files_reused, timings=result.timings, duration_ms=result.duration_ms)
        if result.index and result.index.partial:
            log.warning("job %s: index partial (model=%s, truncated=%s)", job_id, result.index.model, result.index.truncated)

        db.set_repo_status(conn, repo_id, "ready", sha)
        db.update_progress(conn, r, job_id, "done", 100, "done", commit_sha=sha)
        log.info("job %s done (%s: %s): %d files, %s; imports %s; graph %d nodes, %d cycles; %d chunks (%d embedded, %d cached) in %.1fs @ %s",
                 job_id, result.mode, result.reason, result.files_total,
                 ", ".join(f"{k} {v}" for k, v in result.diff.items() if v), result.imports, result.graph_nodes,
                 result.cycles, result.index.chunks_total if result.index else 0,
                 result.index.embedded if result.index else 0, result.index.cached if result.index else 0,
                 result.duration_ms / 1000, sha[:8])
        run_docs(conn, repo_id, job_id, sha)
    except (CloneError, InventoryError) as e:
        # Permanent, user-facing failure: don't retry.
        log.warning("job %s failed: %s", job_id, e)
        db.update_progress(conn, r, job_id, "failed", 0, "failed", str(e))
        db.set_repo_status(conn, repo_id, "failed")
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (repo_id,))
        shutil.rmtree(dest, ignore_errors=True)
