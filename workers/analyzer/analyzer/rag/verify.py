"""Citation verification: never trust the model's citations, check them.

For every sentence of the answer:
  * each citation must name a chunk that was really retrieved ([C3] -> label C3 exists), and a cited line range
    must lie inside the lines that were actually shown to the model for that chunk;
  * invalid citations are removed from the sentence; a sentence left with NO valid citation after losing all
    of its citations is removed entirely (an unsupported claim);
  * a sentence that cites real chunks but names a code identifier (in backticks) that appears nowhere in the
    retrieved code is removed (a hallucinated symbol);
  * a sentence with no citation at all that makes a claim is kept but flagged `uncited` (downgraded);
  * if NO valid citation survives anywhere, the whole answer is replaced by "I couldn't find this in the repo".
Code blocks are kept; if most of their lines are not in the retrieved code the answer is marked partial.
"""
import re
from dataclasses import dataclass, field

from .context import ContextChunk

GROUP = re.compile(r"\[\s*(C\d+(?::\d+(?:-\d+)?)?(?:\s*[,;]\s*C\d+(?::\d+(?:-\d+)?)?)*)\s*\]")
REF = re.compile(r"C(\d+)(?::(\d+)(?:-(\d+))?)?")
BACKTICK = re.compile(r"`([^`\n]+)`")
IDENT = re.compile(r"[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*")
BULLET = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\[(\"'])")
NOT_FOUND_PREFIXES = ("i couldn't find", "i could not find", "i can't find", "i cannot find")
COMMON = frozenset("""None True False self cls str int float bool dict list set tuple bytes object type null undefined true false
string number boolean async await return yield class def function const let var import from raise try except finally if else
for while with as in is not and or lambda print len range Exception Error""".split())
CLAIM_HINTS = re.compile(r"\b(returns?|raises?|calls?|defin\w+|uses?|sets?|creates?|handles?|checks?|reads?|writes?|"
                         r"stores?|loads?|sends?|builds?|inherits?|implements?|is|are|does|takes?|passes?)\b", re.I)


@dataclass
class Citation:
    label: str
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    symbol: str | None = None
    kind: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Claim:
    text: str
    status: str                 # supported | uncited | neutral | removed
    citations: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass
class Verified:
    text: str
    status: str                 # answered | partial | not_found
    citations: list[Citation] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)       # sentences dropped as unsupported
    issues: list[str] = field(default_factory=list)
    discarded: str | None = None                            # the original answer when it was thrown away

    def to_dict(self) -> dict:
        return {"text": self.text, "status": self.status, "citations": [c.to_dict() for c in self.citations],
                "claims": [c.__dict__ for c in self.claims], "removed": self.removed, "issues": self.issues}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def is_not_found(text: str) -> bool:
    return text.strip().lower().replace("’", "'").startswith(NOT_FOUND_PREFIXES)


def _is_claim(sentence: str) -> bool:
    words = re.findall(r"\w+", sentence)
    if len(words) < 5 or sentence.rstrip().endswith("?") or sentence.rstrip().endswith(":"):
        return False
    return bool(BACKTICK.search(sentence) or re.search(r"\d", sentence) or CLAIM_HINTS.search(sentence))


def _split_sentences(line: str) -> list[str]:
    out: list[str] = []
    for s in SENTENCE_SPLIT.split(line.strip()):
        if out and GROUP.fullmatch(s.strip()):      # "... done. [C1]" -> the citation belongs to the sentence before
            out[-1] += " " + s.strip()
        elif s.strip():
            out.append(s.strip())
    return out


def _symbols_missing(sentence: str, blob: str) -> list[str]:
    missing = []
    for token in BACKTICK.findall(GROUP.sub("", sentence)):
        token = token.strip().removesuffix("()")
        if not IDENT.fullmatch(token):
            continue          # an expression, a literal or a path with symbols: not a single identifier
        parts = [p for p in token.split(".") if p and p not in COMMON and len(p) >= 3]
        if any(p not in blob for p in parts):
            missing.append(token)
    return missing


def verify_answer(answer: str, chunks: list[ContextChunk]) -> Verified:
    """Check `answer` against the chunks that were actually given to the model."""
    by_label = {c.label: c for c in chunks}
    blob = "\n".join(c.hit.content + "\n" + c.hit.path + "\n" + (c.hit.symbol or "") for c in chunks)
    blob_norm = _norm(blob)
    v = Verified(text="", status="answered")
    if is_not_found(answer):
        v.status, v.text = "not_found", answer.strip()
        return v

    used: dict[tuple, Citation] = {}
    out_lines: list[str] = []
    in_fence = False
    fence: list[str] = []
    for raw in answer.split("\n"):
        stripped = raw.strip()
        if stripped.startswith("```"):
            if in_fence:
                fence.append(raw)
                body = [ln.strip() for ln in fence[1:-1] if len(ln.strip()) >= 4 and re.search(r"\w", ln)]
                if body and sum(_norm(ln) in blob_norm for ln in body) < 0.6 * len(body):
                    v.issues.append("code_not_in_repo")
                out_lines.extend(fence)
                in_fence, fence = False, []
            else:
                in_fence, fence = True, [raw]
            continue
        if in_fence:
            fence.append(raw)
            continue
        if not stripped or stripped.startswith("#"):
            out_lines.append(raw)
            continue
        bullet = BULLET.match(raw)
        prefix = bullet.group(1) if bullet else ""
        kept: list[str] = []
        for sentence in _split_sentences(raw[len(prefix):]):
            clean, claim = _check_sentence(sentence, by_label, blob, used)
            v.claims.append(claim)
            if claim.status == "removed":
                v.removed.append(sentence)
                v.issues.append(f"removed: {claim.reason}")
                continue
            if claim.status == "uncited":
                v.issues.append("uncited_claim")
            kept.append(clean)
        if kept:
            out_lines.append(prefix + " ".join(kept))
    if in_fence:  # unterminated fence: keep what the model wrote
        out_lines.extend(fence)

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
    v.citations = list(used.values())
    if not v.citations:
        v.discarded = answer.strip()
        v.status = "not_found"
        v.text = "I couldn't find this in the repo. (The model's answer could not be tied to any retrieved code, so it was discarded.)"
        v.issues.append("no_valid_citation")
        return v
    v.text = text
    v.status = "partial" if v.issues else "answered"
    return v


def _check_sentence(sentence: str, by_label: dict[str, ContextChunk], blob: str, used: dict) -> tuple[str, Claim]:
    valid: list[tuple[str, int, int]] = []
    problems: list[str] = []
    for m in GROUP.finditer(sentence):
        for ref in re.split(r"\s*[,;]\s*", m.group(1)):
            label, s, e = REF.fullmatch(ref).group(0).split(":")[0], REF.fullmatch(ref).group(2), REF.fullmatch(ref).group(3)
            ch = by_label.get(label)
            if ch is None:
                problems.append(f"unknown citation {label}")
                continue
            lo, hi = (ch.shown_start, ch.shown_end) if s is None else (int(s), int(e or s))
            if lo > hi or lo < ch.shown_start or hi > ch.shown_end:
                problems.append(f"{ref} is outside {ch.path}:{ch.shown_start}-{ch.shown_end}")
                continue
            valid.append((label, lo, hi))

    def render(m: re.Match) -> str:  # rewrite the groups with only their valid, normalised references
        refs = []
        for ref in re.split(r"\s*[,;]\s*", m.group(1)):
            label = ref.split(":")[0]
            for v_label, lo, hi in valid:
                if v_label == label and (ref == label or ref == f"{label}:{lo}" or ref == f"{label}:{lo}-{hi}"):
                    refs.append(ref)
                    break
        return f"[{', '.join(dict.fromkeys(refs))}]" if refs else ""

    clean = re.sub(r"\s{2,}", " ", GROUP.sub(render, sentence)).strip()
    clean = re.sub(r"\s+([.,;:!?])", r"\1", clean)
    had_citations = bool(GROUP.search(sentence))

    if not valid:
        if had_citations:
            return "", Claim(sentence, "removed", [], "; ".join(problems) or "all citations invalid")
        if _is_claim(sentence):
            return clean, Claim(clean, "uncited", [], "no citation")
        return clean, Claim(clean, "neutral")
    missing = _symbols_missing(sentence, blob)
    if missing:
        return "", Claim(sentence, "removed", [], f"names {', '.join('`' + m + '`' for m in missing)}, which is not in the retrieved code")
    for label, lo, hi in valid:
        ch = by_label[label]
        used.setdefault((label, lo, hi), Citation(label, ch.chunk_id, ch.path, lo, hi, ch.hit.symbol, ch.hit.kind))
    return clean, Claim(clean, "supported", [f"{l}:{lo}-{hi}" for l, lo, hi in valid])
