"""Chunk -> store -> embed. Keyword search works as soon as chunks are saved; vectors are attached after,
in batches, under a time budget, skipping any text that was embedded before (content-hash cache)."""
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from . import config, db
from .chunking import chunk_file, is_indexable
from .chunking.types import Chunk
from .embeddings import Embedder, vec_literal
from .parsing.types import Symbol

log = logging.getLogger("analyzer.indexing")


@dataclass
class IndexStats:
    chunks_total: int = 0
    by_strategy: dict[str, int] = field(default_factory=dict)
    cached: int = 0          # chunk rows that got their vector from the cache
    embedded: int = 0        # distinct texts embedded by the model in this run
    partial: bool = False    # some chunks have no vector (model unavailable / budget exceeded)
    truncated: bool = False  # MAX_CHUNKS reached: some chunks were not stored at all
    model: str | None = None
    seconds: float = 0.0


@dataclass
class SourceFile:
    path: str
    language: str | None
    size: int
    text: str
    symbols: list[Symbol]


def build_chunks(files: Iterable[SourceFile], strategies: Iterable[str] | None = None) -> tuple[list[Chunk], bool]:
    """All chunks for the indexable files, in a stable order. Returns (chunks, truncated)."""
    strategies = tuple(strategies or config.CHUNK_STRATEGIES)
    out: list[Chunk] = []
    for f in sorted(files, key=lambda f: f.path):
        if not is_indexable(f.path, f.language, f.size) or not f.text.strip():
            continue
        for strategy in strategies:
            out.extend(chunk_file(f.path, f.language, f.text, f.symbols, strategy))
    if len(out) > config.MAX_CHUNKS:
        # keep AST chunks first: they are the product; the baseline is optional
        out.sort(key=lambda c: c.strategy != "ast")
        return out[: config.MAX_CHUNKS], True
    return out, False


def embed_pending(conn, embedder: Embedder, repo_id: int, strategies: tuple[str, ...],
                  on_progress: Callable[[float], None] | None = None, budget_s: float | None = None,
                  t0: float | None = None) -> tuple[int, int]:
    """Embed every chunk of `strategies` that has no vector yet. Returns (cached rows, newly embedded texts)."""
    t0 = time.monotonic() if t0 is None else t0
    budget = config.EMBED_BUDGET_S if budget_s is None else budget_s
    cached = db.apply_cached_embeddings(conn, repo_id, embedder.name, strategies)
    total = db.count_pending(conn, repo_id, strategies)
    done, batch = 0, config.EMBED_BATCH * 4
    while done < total:
        if time.monotonic() - t0 > budget:
            log.warning("embedding budget (%ss) exhausted: %d/%d texts embedded", budget, done, total)
            break
        pending = db.pending_embeddings(conn, repo_id, batch, strategies)
        if not pending:
            break
        vectors = embedder.embed_passages([text for _, text in pending])
        db.store_embeddings(conn, repo_id, embedder.name, [(h, vec_literal(v)) for (h, _), v in zip(pending, vectors)])
        done += len(pending)
        if on_progress:
            on_progress(min(1.0, done / total))
    return cached, done


def index_repo(conn, embedder: Embedder | None, repo_id: int, file_ids: dict[str, int], files: Iterable[SourceFile],
               on_progress: Callable[[float], None] | None = None, strategies: Iterable[str] | None = None,
               budget_s: float | None = None, embed_strategies: Iterable[str] | None = None) -> IndexStats:
    t0 = time.monotonic()
    emb = tuple(embed_strategies or config.EMBED_STRATEGIES)
    chunks, truncated = build_chunks(files, strategies)
    stats = IndexStats(chunks_total=len(chunks), truncated=truncated, model=embedder.name if embedder else None)
    for c in chunks:
        stats.by_strategy[c.strategy] = stats.by_strategy.get(c.strategy, 0) + 1
    db.save_chunks(conn, repo_id, file_ids, chunks)

    if embedder is None:
        stats.partial = any(c.strategy in emb for c in chunks)
    else:
        stats.cached, stats.embedded = embed_pending(conn, embedder, repo_id, emb, on_progress, budget_s, t0)
        stats.partial = db.count_pending(conn, repo_id, emb) > 0
    stats.seconds = time.monotonic() - t0
    return stats

    stats.cached = db.apply_cached_embeddings(conn, repo_id, embedder.name)
    total = db.count_pending(conn, repo_id)
    done = 0
    batch = config.EMBED_BATCH * 4
    while done < total:
        if time.monotonic() - t0 > budget:
            log.warning("embedding budget (%ss) exhausted: %d/%d texts embedded", budget, done, total)
            break
        pending = db.pending_embeddings(conn, repo_id, batch)
        if not pending:
            break
        vectors = embedder.embed_passages([text for _, text in pending])
        db.store_embeddings(conn, repo_id, embedder.name, [(h, vec_literal(v)) for (h, _), v in zip(pending, vectors)])
        done += len(pending)
        if on_progress:
            on_progress(min(1.0, done / total))
    stats.embedded = done
    stats.partial = db.count_pending(conn, repo_id) > 0
    stats.seconds = time.monotonic() - t0
    return stats
