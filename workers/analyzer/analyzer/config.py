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
MAX_PARSE_BYTES = int(os.environ.get("MAX_PARSE_BYTES", str(512 * 1024)))
PARSE_TIMEOUT_S = float(os.environ.get("PARSE_TIMEOUT_S", "10"))
# Git history (for churn): bounded by commit count so size/time stay predictable.
HISTORY_MAX_COMMITS = int(os.environ.get("HISTORY_MAX_COMMITS", "500"))
HISTORY_WINDOW_DAYS = int(os.environ.get("HISTORY_WINDOW_DAYS", "90"))
GIT_LOG_TIMEOUT_S = int(os.environ.get("GIT_LOG_TIMEOUT_S", "60"))
COCHANGE_MAX_FILES_PER_COMMIT = int(os.environ.get("COCHANGE_MAX_FILES_PER_COMMIT", "30"))
COCHANGE_TOP_PAIRS = int(os.environ.get("COCHANGE_TOP_PAIRS", "200"))
# Chunking / embeddings / search (Day 5)
CHUNK_MAX_CHARS = int(os.environ.get("CHUNK_MAX_CHARS", "1800"))   # ~450 tokens: fits a 512-token model with header
CHUNK_MIN_CHARS = int(os.environ.get("CHUNK_MIN_CHARS", "300"))    # smaller neighbours get merged
CHUNK_TINY_CHARS = int(os.environ.get("CHUNK_TINY_CHARS", "150"))       # a chunk this small merges with any neighbour
CHUNK_OVERLAP_LINES = int(os.environ.get("CHUNK_OVERLAP_LINES", "3"))
FIXED_CHUNK_CHARS = int(os.environ.get("FIXED_CHUNK_CHARS", "1800"))
FIXED_OVERLAP_CHARS = int(os.environ.get("FIXED_OVERLAP_CHARS", "200"))
MAX_DOC_FILE_BYTES = int(os.environ.get("MAX_DOC_FILE_BYTES", str(200 * 1024)))
MAX_CHUNKS = int(os.environ.get("MAX_CHUNKS", "30000"))
CHUNK_STRATEGIES = tuple(os.environ.get("CHUNK_STRATEGIES", "ast,fixed").split(","))    # chunked + keyword-indexed
# Embedding is the expensive part (~1,800 tokens/s on a laptop CPU), so by default only these get vectors;
# the fixed-size baseline is embedded on demand (python -m analyzer.embed_pending) for the Day 9 comparison.
EMBED_STRATEGIES = tuple(os.environ.get("EMBED_STRATEGIES", "ast").split(","))
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "384"))
EMBED_BATCH = int(os.environ.get("EMBED_BATCH", "32"))
EMBED_THREADS = int(os.environ.get("EMBED_THREADS", "4"))
EMBED_BUDGET_S = int(os.environ.get("EMBED_BUDGET_S", "900"))      # stop embedding after this; keyword search still works
EMBED_CACHE_DIR = os.environ.get("EMBED_CACHE_DIR", os.path.expanduser("~/.cache/codeatlas/models"))
SEARCH_PORT = int(os.environ.get("SEARCH_PORT", "8001"))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
CLAIM_IDLE_MS = int(os.environ.get("CLAIM_IDLE_MS", "60000"))
WORK_DIR = os.environ.get("WORK_DIR", "/tmp/codeatlas-clones")


def events_channel(job_id: int) -> str:
    return f"job:{job_id}:events"
