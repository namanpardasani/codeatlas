"""The RAG pipeline for one question, as a stream of events.

    question -> (rewrite?) -> hybrid retrieval -> (rerank?) -> evidence check -> context -> prompt -> LLM stream
             -> citation verification -> final answer

Events (dicts): status | retrieval | delta | final | error. Weak evidence is refused WITHOUT calling the LLM."""
import re
from collections.abc import Callable, Iterator

from .. import config
from ..llm import LLMError, Message
from ..llm import usage as usage_mod
from ..llm.types import Delta, Usage
from ..search import search
from . import evidence as evidence_mod
from .context import ContextChunk, assemble
from .prompt import build_messages
from .rerank import rerank as rerank_hits
from .rewrite import clean_history, needs_rewrite, rewrite_query
from .verify import verify_answer

NOT_FOUND_TEXT = "I couldn't find this in the repo."
MAX_QUESTION = 1000


def wants_tests(*texts: str) -> bool:
    """Does the question ask about tests? Otherwise test files are excluded from retrieval (they crowd out source)."""
    return bool(re.search(r"\b(tests?|testing|pytest|spec|unit)\b", " ".join(texts), re.I))


def _chunk_info(c: ContextChunk) -> dict:
    h = c.hit
    return {"label": c.label, "chunk_id": h.chunk_id, "path": h.path, "start_line": c.shown_start,
            "end_line": c.shown_end, "symbol": h.symbol, "kind": h.kind, "similarity": h.vector_similarity,
            "vector_rank": h.vector_rank, "keyword_rank": h.keyword_rank, "score": h.score}


def answer(conn, embedder, llm, repo_id: int, question: str, *, history: list[tuple[str, str]] | None = None,
           client_key: str = "anonymous", min_similarity: float | None = None, rewrite: str | None = None,
           reranker: Callable[[str, list[str]], list[float]] | None = None) -> Iterator[dict]:
    question = (question or "").strip()
    history = clean_history((history or [])[-config.RAG_HISTORY_TURNS:])
    if not question or len(question) > MAX_QUESTION:
        yield {"type": "error", "kind": "bad_request", "message": f"Question must be 1..{MAX_QUESTION} characters."}
        return

    tokens_in = tokens_out = 0
    reserved = False

    def reserve() -> None:  # spend budget only when an LLM is actually about to be called
        nonlocal reserved
        if not reserved:
            usage_mod.reserve(conn, client_key)
            reserved = True

    try:
        # 1. standalone query for follow-ups
        query = question
        if needs_rewrite(question, history, rewrite):
            yield {"type": "status", "stage": "rewriting"}
            reserve()
            query, u = rewrite_query(llm, history, question)
            if u:
                tokens_in, tokens_out = tokens_in + u.input_tokens, tokens_out + u.output_tokens

        # 2. retrieval (+ optional rerank)
        yield {"type": "status", "stage": "retrieving"}
        # "how does X work" is answered by source code; test files and docs would otherwise crowd it out
        tests_wanted = wants_tests(question, query)
        result = search(conn, embedder, repo_id, query, mode="hybrid", chunking="ast", limit=config.RAG_CANDIDATES,
                        exclude_tests=not tests_wanted)
        hits = result.hits
        if reranker and hits:
            hits = rerank_hits(hits, query, reranker)

        # 3. is the evidence strong enough?
        ev = evidence_mod.assess(f"{question} {query}" if query != question else question, hits, min_similarity)
        chunks = assemble(hits)
        yield {"type": "retrieval", "query": query, "rewritten": query != question, "evidence": ev.to_dict(),
               "chunks": [_chunk_info(c) for c in chunks], "warnings": result.warnings}
        if not ev.strong or not chunks:
            closest = [_chunk_info(c) for c in chunks[:3]]
            yield {"type": "final", "status": "not_found", "answer": NOT_FOUND_TEXT, "citations": [], "claims": [],
                   "removed": [], "issues": [f"weak evidence: {ev.reason}"], "closest": closest, "model": None,
                   "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}, "llm_called": False}
            return

        # 4. prompt + stream
        messages: list[Message] = build_messages(question, chunks, history)
        yield {"type": "status", "stage": "generating"}
        reserve()
        text = ""
        for ev_ in llm.stream(messages, max_tokens=config.LLM_MAX_TOKENS, temperature=0.1):
            if isinstance(ev_, Delta):
                text += ev_.text
                yield {"type": "delta", "text": ev_.text}
            elif isinstance(ev_, Usage):
                tokens_in, tokens_out = tokens_in + ev_.input_tokens, tokens_out + ev_.output_tokens

        # 5. never trust the citations: verify them
        verified = verify_answer(text, chunks)
        yield {"type": "final", **verified.to_dict(), "answer": verified.text, "model": llm.model,
               "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}, "llm_called": True,
               "retrieved": [_chunk_info(c) for c in chunks]}
    except LLMError as e:
        yield {"type": "error", **e.to_dict()}
    finally:
        if reserved and (tokens_in or tokens_out):
            usage_mod.record(conn, client_key, tokens_in, tokens_out)
