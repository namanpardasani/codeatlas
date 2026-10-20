import json
import subprocess
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parents[4] / "eval" / "results"


def git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                              cwd=Path(__file__).parent).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def save_run(conn, kind: str, label: str, dataset_hash: str, config: dict, summary: dict, items: list | dict,
             write_file: bool = True) -> int:
    run_id = conn.execute(
        """INSERT INTO eval_runs (kind, label, git_sha, dataset_hash, config, summary, items)
           VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb) RETURNING id""",
        (kind, label, git_sha(), dataset_hash, json.dumps(config), json.dumps(summary), json.dumps(items)),
    ).fetchone()[0]
    if write_file:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"{kind}-{run_id}-{label or 'run'}.json").write_text(
            json.dumps({"id": run_id, "kind": kind, "label": label, "git_sha": git_sha(), "dataset_hash": dataset_hash,
                        "config": config, "summary": summary, "items": items}, indent=1, sort_keys=True))
    return run_id


def load_run(conn, run_id: int) -> dict:
    r = conn.execute("SELECT id, kind, label, git_sha, dataset_hash, config, summary, items FROM eval_runs WHERE id = %s",
                     (run_id,)).fetchone()
    if not r:
        raise SystemExit(f"no eval run {run_id}")
    return dict(zip(("id", "kind", "label", "git_sha", "dataset_hash", "config", "summary", "items"), r))


def latest_run(conn, kind: str, label: str | None = None) -> dict | None:
    r = conn.execute("SELECT id FROM eval_runs WHERE kind = %s AND (%s::text IS NULL OR label = %s) ORDER BY id DESC LIMIT 1",
                     (kind, label, label)).fetchone()
    return load_run(conn, r[0]) if r else None
