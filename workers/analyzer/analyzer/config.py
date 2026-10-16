import os


def _database_url() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url
    user = os.environ.get("POSTGRES_USER", "codeatlas")
    pw = os.environ.get("POSTGRES_PASSWORD", "change-me-locally")
    port = os.environ.get("POSTGRES_PORT", "5433")
    db = os.environ.get("POSTGRES_DB", "codeatlas")
    return f"postgresql://{user}:{pw}@127.0.0.1:{port}/{db}"


DATABASE_URL = _database_url()
REDIS_URL = os.environ.get("REDIS_URL", f"redis://127.0.0.1:{os.environ.get('REDIS_PORT', '6380')}")

JOB_STREAM = "analysis:jobs"
JOB_GROUP = "workers"
CONSUMER = os.environ.get("WORKER_NAME", f"worker-{os.getpid()}")

# Limits: analysed repos are untrusted input.
CLONE_TIMEOUT_S = int(os.environ.get("CLONE_TIMEOUT_S", "120"))
MAX_REPO_BYTES = int(os.environ.get("MAX_REPO_BYTES", str(150 * 1024 * 1024)))
MAX_FILES = int(os.environ.get("MAX_FILES", "5000"))
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", str(1024 * 1024)))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
CLAIM_IDLE_MS = int(os.environ.get("CLAIM_IDLE_MS", "60000"))
WORK_DIR = os.environ.get("WORK_DIR", "/tmp/codeatlas-clones")


def events_channel(job_id: int) -> str:
    return f"job:{job_id}:events"
