"""Embedding backends behind one small interface.

* FastEmbedder: BAAI/bge-small-en-v1.5 (MIT, 384 dims, ~67 MB quantized ONNX) via fastembed/ONNX Runtime, CPU only.
  Passages and queries are embedded differently (bge expects a query instruction prefix); fastembed handles it.
* HashEmbedder: deterministic bag-of-words hashing into the same dimension. NOT semantic: it exists so tests and
  offline development exercise the whole retrieval stack without downloading a model.
"""
import hashlib
import math
import os
import threading
from typing import Protocol

from . import config
from .textutil import IDENT, split_identifier


class Embedder(Protocol):
    name: str
    dim: int

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    def __init__(self, model: str | None = None, threads: int | None = None):
        from fastembed import TextEmbedding  # imported lazily: heavy, and not needed for keyword-only paths
        self.name = model or config.EMBED_MODEL
        self.dim = config.EMBED_DIM
        kwargs = dict(cache_dir=config.EMBED_CACHE_DIR, threads=threads or config.EMBED_THREADS)
        try:
            # Cached model: load WITHOUT touching the network. (Contacting HuggingFace to "check for updates"
            # can block for minutes when DNS is flaky, which would freeze the worker / search service.)
            self._model = TextEmbedding(self.name, local_files_only=True, **kwargs)
        except Exception:  # noqa: BLE001  not cached yet: download once (bounded by the HF_HUB_* timeouts)
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
            os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
            self._model = TextEmbedding(self.name, **kwargs)
        self._lock = threading.Lock()  # one inference at a time: bounded CPU, simple semantics

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            return [v.tolist() for v in self._model.embed(texts, batch_size=config.EMBED_BATCH)]

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            return next(iter(self._model.query_embed([text]))).tolist()


class HashEmbedder:
    name = "hash-bow-384"

    def __init__(self, dim: int | None = None):
        self.dim = dim or config.EMBED_DIM

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for ident in IDENT.findall(text):
            for w in {ident.lower(), *split_identifier(ident)}:
                if len(w) < 2:
                    continue
                h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "big")
                v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def vec_literal(v: list[float]) -> str:
    """pgvector text format: '[0.1,0.2,...]' (cast with ::vector)."""
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def get_embedder() -> Embedder:
    """EMBED_BACKEND=fastembed (default) | hash"""
    backend = os.environ.get("EMBED_BACKEND", "fastembed")
    return HashEmbedder() if backend == "hash" else FastEmbedder()


class LazyEmbedder:
    """Loads the model on first use. If it cannot be loaded (offline, corrupt cache) it reports None and
    remembers the failure, so indexing degrades to keyword-only instead of failing the job."""

    def __init__(self, factory=get_embedder):
        self._factory, self._embedder, self._failed = factory, None, False

    def get(self) -> Embedder | None:
        if self._embedder is None and not self._failed:
            try:
                self._embedder = self._factory()
            except Exception as e:  # noqa: BLE001
                import logging
                logging.getLogger("analyzer.embeddings").warning("embedding model unavailable: %s", e)
                self._failed = True
        return self._embedder
