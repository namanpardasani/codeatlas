"""Indexing + retrieval on a tiny fixture repo with known answers (hash embedder: no model download needed)."""
import pytest

from analyzer import db, indexing
from analyzer.embeddings import HashEmbedder
from analyzer.indexing import SourceFile, embed_pending, index_repo
from analyzer.parsing import parse_source
from analyzer.search import rrf_fuse, search
from analyzer.textutil import expand_identifiers, query_terms, to_tsquery

FILES = {
    "src/retry.py": '''import time


def retry_with_backoff(fn, attempts=5, base_delay=0.5):
    """Call fn again after a failure, waiting twice as long each time (exponential backoff)."""
    delay = base_delay
    for attempt in range(attempts):
        try:
            return fn()
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
''',
    "src/auth.py": '''import hashlib


def verify_password(plain, hashed):
    """Check that a user supplied password matches the stored hash."""
    return hashlib.sha256(plain.encode()).hexdigest() == hashed


def create_session_token(user_id):
    """Issue a signed session token for a logged in user."""
    return f"token-{user_id}"
''',
    "src/config.ts": '''export function parseConfig(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\\n")) {
    const [key, value] = line.split("=");
    if (key) out[key.trim()] = (value ?? "").trim();
  }
  return out;
}

export function loadConfigFile(path: string) {
  return parseConfig(require("fs").readFileSync(path, "utf8"));
}
''',
    "src/pool.py": '''class ConnectionPool:
    """Keeps database connections open and hands them out to callers."""

    def __init__(self, size):
        self.free = [object() for _ in range(size)]

    def acquire(self):
        return self.free.pop()

    def release(self, conn):
        self.free.append(conn)
''',
    "README.md": "# Demo\n\nA tiny demo project.\n\n## Installation\n\nRun pip install demo to get started.\n\n## Configuration\n\nSet the DEMO_HOME variable.\n",
}
LANG = {"py": "python", "ts": "typescript", "md": "markdown"}


def source_files(files=None):
    out = []
    for path, text in (files or FILES).items():
        lang = LANG[path.rsplit(".", 1)[-1]]
        syms = parse_source(path, text.encode()).symbols if lang != "markdown" else []
        out.append(SourceFile(path, lang, len(text), text, syms))
    return out


try:
    conn = db.connect()
except Exception:  # noqa: BLE001
    conn = None
needs_db = pytest.mark.skipif(conn is None, reason="Postgres not available")
EMB = HashEmbedder()


@pytest.fixture
def repo():
    rid = conn.execute("INSERT INTO repos (url, full_name) VALUES ('https://github.com/test/search', 'test/search') "
                       "ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id").fetchone()[0]
    ids = db.save_files(conn, rid, "sha", [__import__("analyzer.inventory", fromlist=["FileRecord"]).FileRecord(
        p, LANG[p.rsplit(".", 1)[-1]], len(t), t.count("\n"), "h", False) for p, t in FILES.items()])
    yield rid, ids
    conn.execute("DELETE FROM repos WHERE id = %s", (rid,))
    conn.execute("DELETE FROM embedding_cache WHERE model = %s", (EMB.name,))


def build(rid, ids, embedder=EMB, **kw):
    return index_repo(conn, embedder, rid, ids, source_files(), **kw)


def top(result, n=3):
    return [h.symbol or h.path for h in result.hits[:n]]


def names(result, n=3):
    """Every symbol named by the top-n hits (a merged `group` chunk names several: "a, b")."""
    return {s.strip() for h in result.hits[:n] for s in (h.symbol or h.path).split(",")}


# ---- pure units -------------------------------------------------------------------------------
def test_rrf_scores_are_the_sum_of_reciprocal_ranks():
    fused = dict(rrf_fuse({"v": [1, 2, 3], "k": [3, 1]}, k=60))
    assert fused[1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[3] == pytest.approx(1 / 63 + 1 / 61)
    assert fused[2] == pytest.approx(1 / 62)


def test_rrf_rewards_agreement_over_a_single_first_place():
    # doc 9 is #1 in one list only; doc 5 is #2 in both -> 5 wins
    order = [i for i, _ in rrf_fuse({"v": [9, 5, 1], "k": [7, 5, 2]})]
    assert order[0] == 5


def test_rrf_is_deterministic_and_handles_empty_lists():
    a = rrf_fuse({"v": [1, 2], "k": [2, 1]})
    assert a == rrf_fuse({"k": [2, 1], "v": [1, 2]})
    assert rrf_fuse({"v": [], "k": []}) == []


def test_identifier_aware_terms():
    assert query_terms("getUserName") == ["getusername", "get", "user", "name"]
    assert {"retry", "backoff", "work", "retrywithbackoff"} <= set(query_terms("how does the retry_with_backoff work"))
    assert query_terms("the of and") == []
    assert "user" in expand_identifiers("def getUserName(): pass").split()
    assert to_tsquery(["a-b", "c'd", "e"]) == "ab | cd | e"


# ---- retrieval on the fixture repo ---------------------------------------------------------------
@needs_db
def test_keyword_finds_exact_identifiers_and_descriptions(repo):
    rid, ids = repo
    build(rid, ids)
    assert "parseConfig" in names(search(conn, None, rid, "parseConfig", mode="keyword"), 1)
    assert names(search(conn, None, rid, "exponential backoff retry", mode="keyword"), 1) == {"retry_with_backoff"}
    assert "create_session_token" in names(search(conn, None, rid, "session token", mode="keyword"), 1)
    assert any(n.startswith("ConnectionPool") for n in names(search(conn, None, rid, "ConnectionPool", mode="keyword"), 1))


@needs_db
def test_vector_finds_by_meaning_overlap(repo):
    rid, ids = repo
    build(rid, ids)
    r = search(conn, EMB, rid, "check the user password against the stored hash", mode="vector")
    assert "verify_password" in names(r, 2)
    assert all(h.keyword_rank is None and h.vector_rank for h in r.hits)


@needs_db
def test_hybrid_combines_both_signals_and_reports_the_breakdown(repo):
    rid, ids = repo
    build(rid, ids)
    r = search(conn, EMB, rid, "parseConfig reads key value lines", mode="hybrid")
    best = r.hits[0]
    assert "parseConfig" in (best.symbol or "")
    assert best.vector_rank is not None and best.keyword_rank is not None   # found by both
    assert best.score > 1 / (60 + 5)                                        # RRF of two lists


@needs_db
def test_modes_are_switchable_and_reported(repo):
    rid, ids = repo
    build(rid, ids)
    for mode in ("vector", "keyword", "hybrid"):
        r = search(conn, EMB, rid, "release a connection back to the pool", mode=mode)
        assert r.mode == mode and r.hits
    with pytest.raises(ValueError):
        search(conn, EMB, rid, "x", mode="semantic")


@needs_db
def test_fixed_baseline_is_a_separate_chunk_set(repo):
    rid, ids = repo
    build(rid, ids)
    ast = search(conn, EMB, rid, "backoff", mode="keyword", chunking="ast")
    fixed = search(conn, EMB, rid, "backoff", mode="keyword", chunking="fixed")
    assert ast.hits[0].kind in ("function", "group") and "retry_with_backoff" in ast.hits[0].symbol
    assert fixed.hits[0].kind == "window"
    assert fixed.hits[0].symbol is None and fixed.hits[0].header == "src/retry.py"
    # fixed chunks are not embedded by default (cost), until requested
    v = search(conn, EMB, rid, "backoff", mode="vector", chunking="fixed")
    assert v.hits == [] and v.warnings
    cached, embedded = embed_pending(conn, EMB, rid, ("fixed",))
    assert embedded + cached > 0
    assert search(conn, EMB, rid, "exponential backoff retry", mode="vector", chunking="fixed").hits


@needs_db
def test_filters_and_safe_escaping(repo):
    rid, ids = repo
    build(rid, ids)
    ts = search(conn, None, rid, "config", mode="keyword", language="typescript")
    assert ts.hits and {h.language for h in ts.hits} == {"typescript"}
    assert {h.path for h in search(conn, None, rid, "password", mode="keyword", path_prefix="src/auth").hits} == {"src/auth.py"}
    assert search(conn, None, rid, "password", mode="keyword", path_prefix="%").hits == []   # % is not a wildcard
    assert {h.kind for h in search(conn, None, rid, "connection", mode="keyword", kind="method").hits} <= {"method"}


@needs_db
def test_markdown_sections_are_searchable(repo):
    rid, ids = repo
    build(rid, ids)
    r = search(conn, None, rid, "pip install", mode="keyword")
    assert r.hits[0].path == "README.md" and "Installation" in (r.hits[0].symbol or "")


@needs_db
def test_hostile_and_degenerate_queries_do_not_break_search(repo):
    rid, ids = repo
    build(rid, ids)
    for q in ["'; DROP TABLE chunks; --", "the of and", "!!!", "a" * 400, "( | & ! :* )", "名前"]:
        r = search(conn, EMB, rid, q, mode="hybrid")
        assert isinstance(r.hits, list)
    assert conn.execute("SELECT count(*) FROM chunks WHERE repo_id=%s", (rid,)).fetchone()[0] > 0


# ---- caching and degradation ----------------------------------------------------------------------
@needs_db
def test_unchanged_chunks_are_never_re_embedded(repo):
    rid, ids = repo
    first = build(rid, ids)
    assert first.embedded > 0 and first.cached == 0 and not first.partial
    second = build(rid, ids)                              # identical content
    assert second.embedded == 0 and second.cached > 0 and not second.partial
    changed = dict(FILES)
    changed["src/pool.py"] = FILES["src/pool.py"].replace("self.free.pop()", "self.free.pop(0)")
    third = index_repo(conn, EMB, rid, ids, source_files(changed))
    assert 0 < third.embedded < first.embedded            # only the edited chunk(s)


@needs_db
def test_time_budget_degrades_to_keyword_only(repo):
    rid, ids = repo
    stats = build(rid, ids, budget_s=0)
    assert stats.partial and stats.embedded == 0
    assert search(conn, EMB, rid, "parseConfig", mode="keyword").hits                # keyword works
    h = search(conn, EMB, rid, "parseConfig", mode="hybrid")
    assert h.hits and h.warnings                                                   # hybrid falls back with a warning


@needs_db
def test_no_model_means_keyword_only_not_a_failed_job(repo):
    rid, ids = repo
    stats = build(rid, ids, embedder=None)
    assert stats.partial and stats.model is None and stats.chunks_total > 0
    r = search(conn, None, rid, "session token", mode="hybrid")
    assert r.hits and any("unavailable" in w for w in r.warnings)


@needs_db
def test_reindexing_replaces_chunks_without_duplicates(repo):
    rid, ids = repo
    n1 = build(rid, ids).chunks_total
    build(rid, ids)
    assert conn.execute("SELECT count(*) FROM chunks WHERE repo_id=%s", (rid,)).fetchone()[0] == n1


@needs_db
def test_hnsw_and_gin_indexes_are_used(repo):
    rid, ids = repo
    build(rid, ids)
    idx = {r[0] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE tablename='chunks'")}
    assert {"chunks_embedding_hnsw", "chunks_tsv_gin"} <= idx


# ---- the real model (skipped when it cannot be loaded, e.g. offline) ------------------------------
def _real_embedder():
    try:
        from analyzer.embeddings import FastEmbedder
        return FastEmbedder()
    except Exception:  # noqa: BLE001
        return None


REAL = _real_embedder() if conn is not None else None


@needs_db
@pytest.mark.skipif(REAL is None, reason="embedding model not available")
def test_real_model_finds_the_right_function_by_meaning(repo):
    rid, ids = repo
    index_repo(conn, REAL, rid, ids, source_files())
    try:
        # no literal word overlap with the code: only semantics can match
        r = search(conn, REAL, rid, "repeat an operation when it fails, pausing longer every time", mode="vector")
        assert "retry_with_backoff" in names(r, 3)
        r = search(conn, REAL, rid, "is the entered secret correct for this account", mode="vector")
        assert "verify_password" in names(r, 3)
    finally:
        conn.execute("DELETE FROM embedding_cache WHERE model = %s", (REAL.name,))


@needs_db
def test_source_is_embedded_before_test_files(repo):
    rid, ids = repo
    extra = dict(FILES)
    extra["tests/test_retry.py"] = "def test_retry():\n    assert retry_with_backoff(lambda: 1) == 1\n"
    for p, t in extra.items():
        if p not in ids:
            ids.update(db.save_files(conn, rid, "sha", [__import__("analyzer.inventory", fromlist=["FileRecord"]).FileRecord(
                q, LANG[q.rsplit(".", 1)[-1]], len(x), x.count("\n"), "h", q.startswith("tests/")) for q, x in extra.items()]))
    index_repo(conn, None, rid, ids, source_files(extra))       # chunks saved, nothing embedded
    pending = db.pending_embeddings(conn, rid, 1000, ("ast",))
    assert "tests/test_retry.py" in pending[-1][1] and all("tests/" not in t for _, t in pending[:-1])
