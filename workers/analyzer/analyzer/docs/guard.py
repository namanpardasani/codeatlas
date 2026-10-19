"""Keep generated summaries honest: they may only say what the material they were given supports.

The material is exactly what the model saw (code, child summaries, facts). A sentence is dropped when
  * it puts in backticks a code name that appears nowhere in the material (an invented symbol), or
  * it puts in backticks a file path that is neither a known repo path nor in the material (an invented file), or
  * the words it uses ABOUT the code are mostly absent from the material (an invented behaviour).
A sentence must also be AFFIRMATIVELY grounded: it names something that really is in the material (a backticked symbol or
path), or at least three of its content words are mostly supported by the material. Sentences with neither (a bare "PWNED.",
chit-chat, an instruction) are dropped, as are URLs that are not in the material.
If nothing survives, the caller falls back to the extractive summary."""
import re

from ..rag.verify import BACKTICK, COMMON, IDENT, _content_words, _split_sentences  # same checks as the chat verifier

MIN_SUPPORT = 0.30
FILE_EXT = {"py", "ts", "tsx", "js", "jsx", "mjs", "json", "md", "toml", "yaml", "yml", "css", "html", "sh", "sql", "txt", "cfg", "ini", "go", "rs", "java", "rb"}
URL = re.compile(r"https?://\S+|www\.\S+", re.I)
# Words that make a SPECIFIC technical claim. A summary that uses one the material never mentions is inventing a
# mechanism (measured: a model described a plain function as "a generator function"). Plain word overlap cannot catch
# this, because the rest of the sentence usually matches.
CLAIM_TERMS = frozenset("""generator decorator singleton factory middleware observer iterator recursion recursive closure thread threads
multithreaded multithreading database sql encryption encrypt encrypted decrypt authentication authorization websocket cache caching logging
serialization serialize deserialize parser compiler scheduler dispatcher microservice orm graphql oauth jwt redis kafka docker kubernetes
mutex semaphore daemon plugin plugins interceptor proxy sandbox sandboxed""".split())
ENTRY_WORDS = re.compile(r"entry[- ]?points?|main file|starting point", re.I)
MAX_SENTENCES = 5
MAX_CHARS = 900


def _is_path_like(token: str) -> bool:
    return "/" in token or (IDENT.fullmatch(token) is not None and token.rsplit(".", 1)[-1].lower() in FILE_EXT and "." in token)


def check_summary(text: str, material: str, known_paths: set[str]) -> tuple[str | None, list[str]]:
    """(clean text or None, reasons for what was dropped)."""
    issues: list[str] = []
    text = re.sub(r"^\s*(#+\s*|summary:\s*|description:\s*)", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*\n+\s*", " ", text).strip().strip('"')
    material_words = _content_words(material)
    kept: list[str] = []
    for sentence in _split_sentences(text):
        bad: list[str] = []
        for raw in BACKTICK.findall(sentence):
            tok = raw.strip().removesuffix("()")
            if _is_path_like(tok):
                if tok not in material and tok not in known_paths and not any(p.endswith("/" + tok) for p in known_paths):
                    bad.append(tok)
            elif IDENT.fullmatch(tok):
                parts = [p for p in tok.split(".") if p and p not in COMMON and len(p) >= 3]
                if any(p not in material for p in parts):
                    bad.append(tok)
        if bad:
            issues.append("dropped a sentence naming " + ", ".join(f"`{b}`" for b in bad[:3]) + " (not in the material)")
            continue
        if any(u.rstrip(".,;)") not in material for u in URL.findall(sentence)):
            issues.append("dropped a sentence with a URL that is not in the material")
            continue
        material_lower = material.lower()
        invented = sorted({w for w in re.findall(r"[a-z]+", BACKTICK.sub(" ", sentence).lower())
                           if w in CLAIM_TERMS and w[: max(4, len(w) - 2)] not in material_lower})
        if invented:
            issues.append("dropped a sentence claiming " + ", ".join(invented) + " (the material never mentions it)")
            continue
        words = _content_words(BACKTICK.sub(" ", sentence))
        named = [t for t in BACKTICK.findall(sentence) if t.strip()]
        if len(words) >= 3:
            if len(words & material_words) / len(words) < MIN_SUPPORT:
                issues.append("dropped a sentence whose wording the material does not support")
                continue
        elif not named:
            issues.append("dropped a sentence that names nothing from the material and says too little to verify")
            continue
        kept.append(sentence)
    if not kept:
        return None, issues
    return " ".join(kept[:MAX_SENTENCES])[:MAX_CHARS], issues


def check_entry_points(text: str, entry_points: list[dict]) -> tuple[str | None, list[str]]:
    """Entry points are FACTS read from the repo (package.json, conventional names, `__main__` blocks), not something a
    model may infer: a sentence about entry points may name only the listed ones."""
    allowed = {e["path"] for e in entry_points}
    kept, issues = [], []
    for sentence in _split_sentences(text):
        paths = [t.strip() for t in BACKTICK.findall(sentence) if _is_path_like(t.strip())]
        if ENTRY_WORDS.search(sentence) and any(p not in allowed for p in paths):
            issues.append("dropped an entry-point claim naming a file that is not a known entry point")
            continue
        kept.append(sentence)
    return (" ".join(kept) or None), issues
