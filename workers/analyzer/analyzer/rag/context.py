"""Turn ranked hits into the labelled, numbered context shown to the model, under a token budget."""
from dataclasses import dataclass

from .. import config
from ..llm.types import estimate_tokens
from ..search import Hit


@dataclass
class ContextChunk:
    label: str          # C1, C2 ... (request-scoped id the model cites)
    hit: Hit
    shown_start: int
    shown_end: int      # lines actually included (a long chunk may be cut to fit the budget)
    text: str           # numbered lines

    @property
    def chunk_id(self) -> int:
        return self.hit.chunk_id

    @property
    def path(self) -> str:
        return self.hit.path


def _numbered(lines: list[str], first: int) -> str:
    return "\n".join(f"{first + i:>5}| {ln}" for i, ln in enumerate(lines))


def _overlaps(a: Hit, b: Hit) -> bool:
    if a.path != b.path:
        return False
    inter = min(a.end_line, b.end_line) - max(a.start_line, b.start_line) + 1
    return inter > 0 and inter >= 0.5 * min(a.end_line - a.start_line + 1, b.end_line - b.start_line + 1)


def heading(c: ContextChunk) -> str:
    h = c.hit
    what = f"{h.kind} {h.symbol}" if h.symbol else h.kind
    return f"[{c.label}] {h.path}:{c.shown_start}-{c.shown_end} ({what})"


def assemble(hits: list[Hit], budget_tokens: int | None = None, max_chunks: int | None = None) -> list[ContextChunk]:
    """Best hits first, skipping ones that mostly overlap an already chosen chunk (AST parts overlap by design)."""
    budget = config.RAG_CONTEXT_TOKENS if budget_tokens is None else budget_tokens
    limit = config.RAG_MAX_CHUNKS if max_chunks is None else max_chunks
    chosen: list[ContextChunk] = []
    kept: list[Hit] = []
    for h in hits:
        if len(chosen) >= limit or budget <= 80:
            break
        if any(_overlaps(h, k) for k in kept):
            continue
        lines = h.content.split("\n")
        end = h.end_line
        text = _numbered(lines, h.start_line)
        cost = estimate_tokens(text) + 20
        if cost > budget:
            if not chosen or budget >= 300:  # cut the chunk to what fits (always keep at least the top hit)
                keep_lines = max(3, int(len(lines) * budget / cost))
                lines = lines[:keep_lines]
                end = h.start_line + len(lines) - 1
                text = _numbered(lines, h.start_line) + "\n      …(truncated)"
                cost = estimate_tokens(text) + 20
            else:
                continue
        budget -= cost
        kept.append(h)
        chosen.append(ContextChunk(f"C{len(chosen) + 1}", h, h.start_line, end, text))
    return chosen
