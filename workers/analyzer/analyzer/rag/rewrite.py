"""Query rewriting for follow-up questions ("and how does it handle timeouts?" -> "how does HTTPAdapter handle timeouts").

Retrieval embeds only the new question, so pronouns and ellipsis lose the topic. A rewrite costs one short LLM
call, so it runs only when it can help: there IS history and the question is short or uses referring words."""
import re

from .. import config
from ..llm import LLMError, Message
from ..llm.types import Delta, Usage

REFERRING = re.compile(r"\b(it|its|that|this|those|these|they|them|there|same|above|previous|earlier|also|too|instead)\b", re.I)

REWRITE_SYSTEM = ("Rewrite the user's LAST question as one standalone search query for a code repository, "
                  "resolving pronouns and omissions using the earlier turns. Output ONLY the query (max 20 words), "
                  "no quotes, no explanation.")


def needs_rewrite(question: str, history: list[tuple[str, str]], mode: str | None = None) -> bool:
    mode = config.RAG_REWRITE if mode is None else mode
    if mode == "off" or not history:
        return False
    if mode == "always":
        return True
    return len(question.split()) <= 8 or bool(REFERRING.search(question))


def rewrite_query(llm, history: list[tuple[str, str]], question: str) -> tuple[str, Usage | None]:
    """Standalone query; on any failure falls back to the original question (retrieval still works)."""
    turns = "\n".join(f"User: {q[:300]}\nAssistant: {a[:300]}" for q, a in history[-config.RAG_HISTORY_TURNS:])
    messages = [Message("system", REWRITE_SYSTEM), Message("user", f"EARLIER TURNS:\n{turns}\n\nLAST QUESTION: {question}")]
    text, usage = "", None
    try:
        for ev in llm.stream(messages, max_tokens=48, temperature=0.0):
            if isinstance(ev, Delta):
                text += ev.text
            elif isinstance(ev, Usage):
                usage = ev
    except LLMError:
        return question, usage
    text = text.strip().strip('"').splitlines()[0] if text.strip() else ""
    return (text[:200] if len(text) >= 3 else question), usage
