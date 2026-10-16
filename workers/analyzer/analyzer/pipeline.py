import logging
import shutil
from pathlib import Path

from . import config, db
from .clone import CloneError, clone
from .inventory import InventoryError, build_inventory

log = logging.getLogger("analyzer.pipeline")


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

        db.update_progress(conn, r, job_id, "inventory", 40, commit_sha=sha)
        records = build_inventory(dest)

        db.update_progress(conn, r, job_id, "saving", 85, commit_sha=sha)
        db.save_files(conn, repo_id, sha, records)

        db.set_repo_status(conn, repo_id, "ready", sha)
        db.update_progress(conn, r, job_id, "done", 100, "done", commit_sha=sha)
        log.info("job %s done: %d files @ %s", job_id, len(records), sha[:8])
    except (CloneError, InventoryError) as e:
        # Permanent, user-facing failure: don't retry.
        log.warning("job %s failed: %s", job_id, e)
        db.update_progress(conn, r, job_id, "failed", 0, "failed", str(e))
        db.set_repo_status(conn, repo_id, "failed")
    finally:
        shutil.rmtree(dest, ignore_errors=True)
