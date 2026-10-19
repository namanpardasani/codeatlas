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


CITATION_TAGS = re.compile(r"\s*\[\s*C\d+(?::\d+(?:-\d+)?)?(?:\s*[,;]\s*C\d+(?::\d+(?:-\d+)?)?)*\s*\]")
BACKTICKED = re.compile(r"`([A-Za-z_][\w.]{2,})`")


def clean_history(history: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Earlier answers contain [C1]-style tags that referred to THAT turn's excerpts; in a new prompt the same
    label would point at different code, so the tags are removed (and a stray leading bracket from the model too)."""
    return [(q, CITATION_TAGS.sub("", a).lstrip("[ ").strip()) for q, a in history]


def enrich_question(history: list[tuple[str, str]], question: str) -> str:
    """Deterministic fallback "rewrite": the question plus the code names the last turn was about."""
    names: list[str] = []
    for q, a in reversed(history):
        for n in BACKTICKED.findall(a) + re.findall(r"\b[A-Za-z]+_[A-Za-z_]+\b", q):
            if n not in names:
                names.append(n)
        if names:
            break
    return f"{question} {' '.join(names[:3])}".strip()


def sane_rewrite(text: str, question: str, history: list[tuple[str, str]]) -> bool:
    """Reject rewrites that look like an echo or garbage (seen from a 1.5B model)."""
    if not text or len(text.split()) > 30 or len(text) > 220 or "[" in text or "`" in text:
        return False
    low = {w for w in re.findall(r"[a-z]{4,}", text.lower())}
    ctx = {w for w in re.findall(r"[a-z]{4,}", (question + " " + " ".join(q + " " + a for q, a in history)).lower())}
    return len(low & ctx) >= 1 and len(set(text.lower().split())) >= 0.6 * len(text.split())


def rewrite_query(llm, history: list[tuple[str, str]], question: str) -> tuple[str, Usage | None]:
    """Standalone query. A failing or implausible LLM rewrite falls back to a deterministic enrichment."""
    history = clean_history(history)
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
        return enrich_question(history, question), usage
    text = text.strip().strip('"').splitlines()[0] if text.strip() else ""
    return (text if sane_rewrite(text, question, history) else enrich_question(history, question)), usage
