"""Optional cross-encoder reranking (RAG_RERANK=cross-encoder). Off by default.

Is it worth it? A bi-encoder (our vectors) embeds query and chunk separately: fast, but coarse. A cross-encoder reads
(query, chunk) TOGETHER and scores relevance directly: usually a clear precision win at the top of the list, at the
cost of one model pass per candidate (12 pairs ~ 3,500 tokens ~ 2 s on this laptop CPU, on top of ~15 ms retrieval).
Whether that is worth 2 s is an empirical question; Day 9's evaluation compares recall@k/MRR with and without it."""
from collections.abc import Callable

from ..search import Hit


class CrossEncoderReranker:
    def __init__(self, model: str = "Xenova/ms-marco-MiniLM-L-6-v2"):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        from .. import config
        try:
            self._enc = TextCrossEncoder(model_name=model, cache_dir=config.EMBED_CACHE_DIR, local_files_only=True)
        except Exception:  # noqa: BLE001  not cached yet: download once
            self._enc = TextCrossEncoder(model_name=model, cache_dir=config.EMBED_CACHE_DIR)
        self.name = model

    def scores(self, query: str, docs: list[str]) -> list[float]:
        return [float(s) for s in self._enc.rerank(query, docs)]


def rerank(hits: list[Hit], query: str, scorer: Callable[[str, list[str]], list[float]], top: int | None = None) -> list[Hit]:
    """Reorder `hits` by cross-encoder score (stable for ties). `scorer(query, docs) -> scores`."""
    if len(hits) < 2:
        return hits
    scores = scorer(query, [f"{h.header}\n{h.content[:1500]}" for h in hits])
    order = sorted(range(len(hits)), key=lambda i: (-scores[i], i))
    out = [hits[i] for i in order]
    return out[:top] if top else out
