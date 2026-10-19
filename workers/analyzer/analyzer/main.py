import logging
import time

import redis

from . import config, db
from .embeddings import LazyEmbedder
from .pipeline import run_job

log = logging.getLogger("analyzer")


def ensure_group(r: redis.Redis) -> None:
    try:
        r.xgroup_create(config.JOB_STREAM, config.JOB_GROUP, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def handle(conn, r, msg_id: str, fields: dict, embedders=None) -> None:
    try:
        run_job(conn, r, int(fields["jobId"]), embedders)
    except Exception:
        # Unexpected crash: leave message un-acked so it is reclaimed and retried
        # (run_job bumps `attempts`, which caps retries).
        log.exception("job message %s crashed; will be retried", msg_id)
        return
    r.xack(config.JOB_STREAM, config.JOB_GROUP, msg_id)


def reclaim_stale(conn, r, embedders=None) -> None:
    """Take over messages whose consumer died mid-job."""
    start = "0-0"
    while True:
        res = r.xautoclaim(config.JOB_STREAM, config.JOB_GROUP, config.CONSUMER,
                           min_idle_time=config.CLAIM_IDLE_MS, start_id=start, count=10)
        start, messages = res[0], res[1]
        for msg_id, fields in messages:
            log.info("reclaimed %s", msg_id)
            handle(conn, r, msg_id, fields, embedders)
        if start in ("0-0", b"0-0") or not messages:
            return


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # socket_timeout must exceed the XREADGROUP block time (5s) or idle waits look like failures
    r = redis.Redis.from_url(config.REDIS_URL, decode_responses=True,
                             socket_timeout=30, socket_connect_timeout=5, health_check_interval=30)
    conn = db.connect()
    embedders = LazyEmbedder()  # model loaded on first job, shared by all jobs of this worker
    ensure_group(r)
    log.info("worker %s ready", config.CONSUMER)
    last_reclaim = 0.0
    while True:
        if time.monotonic() - last_reclaim > 30:
            reclaim_stale(conn, r, embedders)
            last_reclaim = time.monotonic()
        resp = r.xreadgroup(config.JOB_GROUP, config.CONSUMER, {config.JOB_STREAM: ">"}, count=1, block=5000)
        for _stream, messages in resp or []:
            for msg_id, fields in messages:
                handle(conn, r, msg_id, fields, embedders)


if __name__ == "__main__":
    main()
