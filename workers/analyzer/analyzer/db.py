import json

import psycopg
import redis
from psycopg.types.json import Jsonb

from . import config
from .inventory import FileRecord
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
                "UPDATE files SET parse_status=%s, parse_error=%s, exports=%s WHERE id=%s",
                [(r.status, r.error, Jsonb(r.exports), fid) for fid, r in results.items()],
            )
            cur.executemany(
                """INSERT INTO symbols (repo_id, file_id, idx, name, kind, start_line, end_line, params,
                                        parent_name, is_exported, is_default_export, has_doc, signature)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(repo_id, fid, i, s.name, s.kind, s.start_line, s.end_line, Jsonb(s.params),
                  s.parent, s.is_exported, s.is_default_export, s.has_doc, s.signature)
                 for fid, r in results.items() for i, s in enumerate(r.symbols)],
            )
            cur.executemany(
                """INSERT INTO imports_raw (repo_id, file_id, idx, specifier, kind, names, level, line, is_type_only)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(repo_id, fid, i, im.specifier, im.kind, Jsonb(im.names), im.level, im.line, im.is_type_only)
                 for fid, r in results.items() for i, im in enumerate(r.imports)],
            )
