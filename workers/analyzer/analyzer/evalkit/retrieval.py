"""Retrieval evaluation: the same questions through every retrieval variant, scored on where the correct
file/symbol lands in the ranking."""
from dataclasses import dataclass

from .. import config
from ..rag.pipeline import wants_tests
from ..rag.rerank import rerank as rerank_hits
from ..search import search
from . import metrics
from .relevance import covered_by, resolve_targets
from .schema import Dataset

K = 10
RERANK_CANDIDATES = 20


@dataclass(frozen=True)
class Variant:
    chunking: str      # ast | fixed
    mode: str          # vector | keyword | hybrid
    rerank: bool = False

    @property
    def name(self) -> str:
        return f"{self.chunking}/{self.mode}" + ("+rerank" if self.rerank else "")


ALL_VARIANTS = [Variant(c, m) for c in ("fixed", "ast") for m in ("vector", "keyword", "hybrid")] + [
    Variant("fixed", "hybrid", True), Variant("ast", "hybrid", True)]


def repo_ids(conn, ds: Dataset) -> tuple[dict[str, int], list[str]]:
    ids, problems = {}, []
    for repo in sorted({q.repo for q in ds.questions}):
        r = conn.execute("SELECT id, status FROM repos WHERE full_name = %s", (repo,)).fetchone()
        if not r:
            problems.append(f"repo {repo} has not been analysed (submit it in the app first)")
        elif r[1] != "ready":
            problems.append(f"repo {repo} is {r[1]}, not ready")
        else:
            ids[repo] = r[0]
    return ids, problems


def check_ground_truth(conn, ds: Dataset) -> tuple[dict[str, int], list[str]]:
    ids, problems = repo_ids(conn, ds)
    for q in ds.questions:
        if q.repo in ids:
            _, p = resolve_targets(conn, ids[q.repo], q)
            problems += p
    return ids, problems


def unembedded(conn, ids: dict[str, int], chunkings: set[str]) -> dict[tuple[str, str], int]:
    out = {}
    for repo, rid in ids.items():
        for c in chunkings:
            n = conn.execute("SELECT count(*) FROM chunks WHERE repo_id = %s AND strategy = %s AND embedding IS NULL",
                             (rid, c)).fetchone()[0]
            if n:
                out[(repo, c)] = n
    return out


def run_variant(conn, embedder, scorer, ds: Dataset, ids: dict[str, int], v: Variant) -> tuple[dict, list[dict]]:
    items, per_q = [], []
    for q in ds.questions:
        if not q.answerable:
            continue                                  # nothing to retrieve
        rid = ids[q.repo]
        targets, _ = resolve_targets(conn, rid, q)
        excl = not wants_tests(q.question)            # same rule as the chat pipeline
        res = search(conn, embedder if v.mode != "keyword" else None, rid, q.question, mode=v.mode, chunking=v.chunking,
                     limit=RERANK_CANDIDATES if v.rerank else K, exclude_tests=excl)
        hits = res.hits
        if v.rerank and hits:
            hits = rerank_hits(hits, q.question, scorer)
        hits = hits[:K]
        covered = [covered_by(h.path, h.start_line, h.end_line, targets) for h in hits]
        per_q.append((covered, len(targets)))
        truth_files = set(q.files)
        items.append({"id": q.id, "repo": q.repo, "n_targets": len(targets), "first_rank": metrics.first_hit_rank(covered),
                      "file_in_top_k": any(h.path in truth_files for h in hits),
                      "found": sorted({i for c in covered for i in c}),
                      "top": [{"path": h.path, "lines": [h.start_line, h.end_line], "symbol": h.symbol,
                               "relevant": bool(c)} for h, c in zip(hits[:5], covered[:5])],
                      "warnings": res.warnings})
    summary = metrics.retrieval_summary(per_q)
    summary["mrr_ci95"] = metrics.bootstrap_ci([metrics.reciprocal_rank(c) for c, _ in per_q])
    summary["hit@5_ci95"] = metrics.bootstrap_ci([1.0 if metrics.hit_at_k(c, 5) else 0.0 for c, _ in per_q])
    return summary, items


def run_retrieval(conn, embedder, scorer, ds: Dataset, ids: dict[str, int], variants: list[Variant]) -> tuple[dict, dict]:
    summary, items = {}, {}
    for v in variants:
        summary[v.name], items[v.name] = run_variant(conn, embedder, scorer, ds, ids, v)
    return summary, items


def run_config(variants: list[Variant], embedder_name: str, reranker_name: str | None) -> dict:
    return {"variants": [v.name for v in variants], "k": K, "rerank_candidates": RERANK_CANDIDATES,
            "embedder": embedder_name, "reranker": reranker_name, "rrf_k": 60,
            "ast_max_chars": getattr(config, "CHUNK_MAX_CHARS", None)}
