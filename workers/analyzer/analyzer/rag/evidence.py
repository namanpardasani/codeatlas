"""Is the retrieved evidence strong enough to answer? Decided BEFORE calling the LLM: a weak result is refused
without spending a token, which both saves budget and removes the main source of hallucination (asking a model
to answer from irrelevant code).

Rules (thresholds calibrated on psf/requests: answerable questions scored 0.733-0.813 best vector similarity,
unanswerable 0.508-0.684, so 0.70 sits in the gap; re-check on Day 9 with more repos):
  1. STRONG if some hit's vector (cosine) similarity >= min_similarity;
  2. STRONG if the query names an identifier (snake_case / camelCase / dotted) that appears verbatim in a hit
     (an exact symbol lookup needs no semantic similarity);
  3. without vectors (model unavailable): STRONG if the top hit contains >= 60% of the query terms;
  4. otherwise WEAK.
"""
import re
from dataclasses import dataclass

from .. import config
from ..search import Hit
from ..textutil import query_terms

IDENT_LIKE = re.compile(r"\b(?:[A-Za-z]+(?:_[A-Za-z0-9]+)+|[a-z]+(?:[A-Z][a-z0-9]+)+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+|[A-Za-z_]\w*\.[A-Za-z_]\w+)\b")


@dataclass
class Evidence:
    strong: bool
    best_similarity: float | None
    reason: str

    def to_dict(self) -> dict:
        return {"strong": self.strong, "best_similarity": self.best_similarity, "reason": self.reason}


def identifiers_in(query: str) -> list[str]:
    return list(dict.fromkeys(m.group(0) for m in IDENT_LIKE.finditer(query)))


def assess(query: str, hits: list[Hit], min_similarity: float | None = None) -> Evidence:
    threshold = config.RAG_MIN_SIMILARITY if min_similarity is None else min_similarity
    if not hits:
        return Evidence(False, None, "no matching code was retrieved")
    sims = [h.vector_similarity for h in hits if h.vector_similarity is not None]
    best = max(sims) if sims else None
    if best is not None and best >= threshold:
        return Evidence(True, best, f"best vector similarity {best:.2f} >= {threshold:.2f}")
    for ident in identifiers_in(query):
        if any(ident in h.content or ident in (h.symbol or "") for h in hits):
            return Evidence(True, best, f"identifier `{ident}` appears in the retrieved code")
    if best is None:  # no vector signal at all: fall back to term coverage of the best keyword hit
        terms = query_terms(query)
        if terms:
            text = (hits[0].header + hits[0].content).lower()
            coverage = sum(t in text for t in terms) / len(terms)
            if coverage >= 0.6:
                return Evidence(True, None, f"top keyword hit contains {coverage:.0%} of the query terms")
        return Evidence(False, None, "keyword-only retrieval with weak term overlap")
    return Evidence(False, best, f"best vector similarity {best:.2f} < {threshold:.2f} and no named identifier matched")
