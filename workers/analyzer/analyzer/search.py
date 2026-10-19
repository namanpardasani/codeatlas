"""Hybrid code search: pgvector similarity + Postgres full-text, fused with Reciprocal Rank Fusion.

Switchable per request (Day 9 compares them):
    mode     = vector | keyword | hybrid
    chunking = ast | fixed          (which chunk set to search; `fixed` is the fixed-size baseline)
"""
import time
from dataclasses import asdict, dataclass, field

from .embeddings import Embedder, vec_literal
from .textutil import query_terms, to_tsquery

MODES = ("vector", "keyword", "hybrid")
CHUNKINGS = ("ast", "fixed")
RRF_K = 60
MAX_LIMIT = 50


@dataclass
class Hit:
    chunk_id: int
    path: str
    language: str | None
    kind: str
    symbol: str | None
    parent: str | None
    start_line: int
    end_line: int
    header: str
    content: str
    score: float                      # hybrid: RRF; vector: cosine similarity; keyword: ts_rank_cd
    vector_rank: int | None = None
    vector_similarity: float | None = None
    keyword_rank: int | None = None
    keyword_score: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchResult:
    hits: list[Hit]
    terms: list[str]
    mode: str
    chunking: str
    warnings: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {**asdict(self), "hits": [h.to_dict() for h in self.hits]}


def rrf_fuse(rankings: dict[str, list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank_in_list(d)), rank starting at 1.
    Returns [(id, score)] best first; ties break on the best individual rank, then id (deterministic)."""
    score: dict[int, float] = {}
    best: dict[int, int] = {}
    for ids in rankings.values():
        for rank, i in enumerate(ids, 1):
            score[i] = score.get(i, 0.0) + 1.0 / (k + rank)
            best[i] = min(best.get(i, rank), rank)
    return sorted(score.items(), key=lambda kv: (-kv[1], best[kv[0]], kv[0]))


def _like_prefix(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


TEST_PATH_SQL = (r" AND NOT (path ~* '(^|/)(tests?|__tests__|specs?)/' OR path ~* '(^|/)test_[^/]*$'"
                 r" OR path ~* '[._](test|spec)\.[a-z]+$')")


def _filters(language, path_prefix, kind, exclude_tests=False) -> tuple[str, dict]:
    sql, params = (TEST_PATH_SQL if exclude_tests else ""), {}
    if language:
        sql += " AND language = %(language)s"
        params["language"] = language
    if path_prefix:
        sql += " AND path LIKE %(prefix)s ESCAPE '\\'"
        params["prefix"] = _like_prefix(path_prefix)
    if kind:
        sql += " AND kind = %(kind)s"
        params["kind"] = kind
    return sql, params


def search(conn, embedder: Embedder | None, repo_id: int, query: str, *, mode: str = "hybrid",
           chunking: str = "ast", limit: int = 10, language: str | None = None, path_prefix: str | None = None,
           kind: str | None = None, candidates: int = 50, exclude_tests: bool = False) -> SearchResult:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if chunking not in CHUNKINGS:
        raise ValueError(f"chunking must be one of {CHUNKINGS}")
    limit = max(1, min(limit, MAX_LIMIT))
    terms = query_terms(query)
    out = SearchResult([], terms, mode, chunking)
    fsql, fparams = _filters(language, path_prefix, kind, exclude_tests)
    base = {"repo": repo_id, "strategy": chunking, "k": candidates, **fparams}

    vec: list[tuple[int, float]] = []
    if mode in ("vector", "hybrid"):
        t = time.perf_counter()
        if embedder is None:
            out.warnings.append("embedding model unavailable: vector search skipped")
        else:
            q = vec_literal(embedder.embed_query(query))
            out.timings_ms["embed_query"] = round((time.perf_counter() - t) * 1000, 1)
            t = time.perf_counter()
            with conn.transaction():
                # filtered ANN: keep scanning the HNSW graph until enough rows pass repo/strategy/filters
                conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
                conn.execute("SET LOCAL hnsw.ef_search = 100")
                conn.execute("SET LOCAL hnsw.max_scan_tuples = 20000")
                vec = conn.execute(
                    f"""SELECT id, 1 - (embedding <=> %(q)s::vector) AS sim FROM chunks
                        WHERE repo_id = %(repo)s AND strategy = %(strategy)s AND embedding IS NOT NULL
                          AND embed_model = %(model)s {fsql}
                        ORDER BY embedding <=> %(q)s::vector LIMIT %(k)s""",
                    {**base, "q": q, "model": embedder.name}).fetchall()
            out.timings_ms["vector"] = round((time.perf_counter() - t) * 1000, 1)
            if not vec:
                out.warnings.append("no embedded chunks for this repo/chunking (index still building?)")

    kw: list[tuple[int, float]] = []
    if mode in ("keyword", "hybrid"):
        t = time.perf_counter()
        tsq = to_tsquery(terms)
        if tsq:
            kw = conn.execute(
                f"""SELECT id, ts_rank_cd(tsv, q) AS score FROM chunks, to_tsquery('simple', %(tsq)s) q
                    WHERE repo_id = %(repo)s AND strategy = %(strategy)s AND tsv @@ q {fsql}
                    ORDER BY score DESC, id LIMIT %(k)s""",
                {**base, "tsq": tsq}).fetchall()
        out.timings_ms["keyword"] = round((time.perf_counter() - t) * 1000, 1)

    vec_rank = {i: r for r, (i, _) in enumerate(vec, 1)}
    kw_rank = {i: r for r, (i, _) in enumerate(kw, 1)}
    vec_sim, kw_score = dict(vec), dict(kw)

    if mode == "hybrid":
        ordered = rrf_fuse({"vector": [i for i, _ in vec], "keyword": [i for i, _ in kw]})
    elif mode == "vector":
        ordered = [(i, s) for i, s in vec]
    else:
        ordered = [(i, s) for i, s in kw]
    ordered = ordered[:limit]
    if not ordered:
        return out

    rows = {r[0]: r for r in conn.execute(
        """SELECT id, path, language, kind, symbol, parent_name, start_line, end_line, header, content
           FROM chunks WHERE id = ANY(%s)""", ([i for i, _ in ordered],)).fetchall()}
    for cid, score in ordered:
        r = rows[cid]
        out.hits.append(Hit(
            chunk_id=cid, path=r[1], language=r[2], kind=r[3], symbol=r[4], parent=r[5], start_line=r[6],
            end_line=r[7], header=r[8], content=r[9], score=round(float(score), 6),
            vector_rank=vec_rank.get(cid), vector_similarity=round(vec_sim[cid], 4) if cid in vec_sim else None,
            keyword_rank=kw_rank.get(cid), keyword_score=round(float(kw_score[cid]), 4) if cid in kw_score else None))
    return out
