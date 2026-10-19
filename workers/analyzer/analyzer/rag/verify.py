"""Citation verification: never trust the model's citations, check them.

For every sentence of the answer:
  * each citation must name a chunk that was really retrieved ([C3] -> label C3 exists), and a cited line range
    must lie inside the lines that were actually shown to the model for that chunk;
  * invalid citations are removed from the sentence; a sentence left with NO valid citation after losing all
    of its citations is removed entirely (an unsupported claim);
  * a sentence that cites real chunks but names a code identifier (in backticks) that appears nowhere in the
    retrieved code is removed (a hallucinated symbol);
  * the words a sentence says ABOUT the code must appear in the chunk(s) it cites (>= RAG_MIN_SUPPORT of them): a sentence
    that says something its cited code does not contain is removed (a cheap stand-in for entailment checking);
  * a sentence with no citation that names code identifiers is checked the same way (a symbol that exists in
    none of the retrieved code removes it); if all its identifiers occur in ONE retrieved chunk, that chunk is
    attached as an INFERRED citation (narrowest matching lines, flagged `inferred`, never passed off as the
    model's own citation): small models often answer correctly but forget to cite;
  * any other uncited claim is kept but flagged `uncited` (downgraded);
  * if NO valid citation survives anywhere, the whole answer is replaced by "I couldn't find this in the repo".
Code blocks are kept; if most of their lines are not in the retrieved code the answer is marked partial.
"""
import re
from dataclasses import dataclass, field

from .. import config
from ..textutil import STOPWORDS, split_identifier
from .context import ContextChunk
from .evidence import IDENT_LIKE

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
    inferred: bool = False      # attached by us (identifier match), not cited by the model

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Claim:
    text: str
    status: str                 # supported | inferred | uncited | neutral | removed
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
    # any ordinary statement counts: questions, headings and very short connective sentences do not
    return not (len(words) < 5 or sentence.rstrip().endswith(("?", ":")))


GENERIC = frozenset("""method function class code file files returns return takes take used uses using use which that this
these those with from into also when then them they there their have has been being will would should could does doing
done first second next after before while where about other more most some such only both each every other based like
object value values parameter parameters argument arguments instance call called calls calling result results""".split())
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


def _stem(w: str) -> str:
    """Crude suffix stripping so `sleeps`/`sleep`, `attempts`/`attempt`, `redirected`/`redirect` match."""
    if w.endswith("ies") and len(w) > 5:
        return w[:-3] + "y"
    for suffix, minlen in (("ing", 6), ("ed", 5), ("es", 5)):
        if w.endswith(suffix) and len(w) >= minlen:
            return w[: -len(suffix)]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 4:
        return w[:-1]
    return w


def _content_words(text: str) -> set[str]:
    words: set[str] = set()
    for tok in WORD.findall(GROUP.sub("", text)):
        for w in (split_identifier(tok) if ("_" in tok or tok != tok.lower()) else [tok.lower()]):
            if len(w) >= 4 and w not in STOPWORDS and w not in GENERIC:
                words.add(_stem(w))
    return words


def _support(sentence: str, chunks: list[ContextChunk]) -> tuple[float, float] | None:
    """(score, required): how much of what the sentence says is found in `chunks`.

    A sentence that names `resolve_redirects` gets overlap "for free" from the identifier, so when it has at least 3
    OTHER content words the score uses only those (what it claims ABOUT the code, e.g. "encrypts", "billing",
    "caches"). Measured on real model output: honest sentences scored 50-100%, invented or parroted ones 0-25%.
    Very short sentences are judged on all their words with a lenient bar. None = too little to judge."""
    text = GROUP.sub("", sentence)
    prose = _content_words(BACKTICK.sub(" ", text))
    words, required = (prose, config.RAG_MIN_SUPPORT) if len(prose) >= 3 else (_content_words(text), config.RAG_MIN_SUPPORT_SHORT)
    if len(words) < 3:
        return None
    hay = _content_words(" ".join(c.hit.content + " " + c.hit.path + " " + (c.hit.symbol or "") for c in chunks))
    return len(words & hay) / len(words), required


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
            clean, claim = _check_sentence(sentence, by_label, blob, used, chunks)
            v.claims.append(claim)
            if claim.status == "removed":
                v.removed.append(sentence)
                v.issues.append(f"removed: {claim.reason}")
                continue
            if claim.status == "uncited":
                v.issues.append("uncited_claim")
            if claim.status == "inferred":
                v.issues.append("citations_inferred")
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
    v.issues = list(dict.fromkeys(v.issues))
    v.status = "partial" if v.issues else "answered"
    return v


def _check_sentence(sentence: str, by_label: dict[str, ContextChunk], blob: str, used: dict,
                    chunks: list[ContextChunk] | None = None) -> tuple[str, Claim]:
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
        if not _is_claim(sentence):
            return clean, Claim(clean, "neutral")
        missing = _symbols_missing(sentence, blob)
        if missing:
            return "", Claim(sentence, "removed", [], f"names {', '.join('`' + m + '`' for m in missing)}, which is not in the retrieved code")
        inferred = _infer_citation(clean, chunks or [])
        if inferred:
            label, lo, hi = inferred
            ch = by_label[label]
            used.setdefault((label, lo, hi), Citation(label, ch.chunk_id, ch.path, lo, hi, ch.hit.symbol, ch.hit.kind, inferred=True))
            tagged = re.sub(r"([.!?]?)$", rf" [{label}:{lo}-{hi}]\1", clean, count=1)
            return tagged, Claim(tagged, "inferred", [f"{label}:{lo}-{hi}"], "citation inferred from identifiers")
        support = _support(sentence, chunks or [])
        if support is not None and support[0] < support[1]:
            return "", Claim(sentence, "removed", [], f"not supported by any retrieved code (support {support[0]:.0%})")
        return clean, Claim(clean, "uncited", [], "no citation")
    missing = _symbols_missing(sentence, blob)
    if missing:
        return "", Claim(sentence, "removed", [], f"names {', '.join('`' + m + '`' for m in missing)}, which is not in the retrieved code")
    cited = [by_label[label] for label in dict.fromkeys(l for l, _, _ in valid)]
    support = _support(sentence, cited)
    if support is not None and support[0] < support[1]:
        return "", Claim(sentence, "removed", [], f"the cited code does not contain what it says (support {support[0]:.0%})")
    for label, lo, hi in valid:
        ch = by_label[label]
        used.setdefault((label, lo, hi), Citation(label, ch.chunk_id, ch.path, lo, hi, ch.hit.symbol, ch.hit.kind))
    return clean, Claim(clean, "supported", [f"{l}:{lo}-{hi}" for l, lo, hi in valid])


def _identifiers(sentence: str) -> list[str]:
    """Code identifiers a sentence talks about: backticked single identifiers and bare snake_case / CamelCase / dotted names."""
    text = GROUP.sub("", sentence)
    found = [t.strip().removesuffix("()") for t in BACKTICK.findall(text)]
    found += [m.group(0) for m in IDENT_LIKE.finditer(BACKTICK.sub(" ", text))]
    out = []
    for tok in found:
        if IDENT.fullmatch(tok) and tok not in COMMON and len(tok) >= 3:
            out.append(tok)
    return list(dict.fromkeys(out))


def _infer_citation(sentence: str, chunks: list[ContextChunk]) -> tuple[str, int, int] | None:
    """The retrieved chunk that contains every identifier of the sentence, with the narrowest matching lines."""
    idents = _identifiers(sentence)
    if not idents:
        return None
    best = None
    for c in chunks:
        hay = c.hit.content + "\n" + (c.hit.symbol or "")
        if not all(i.split(".")[-1] in hay for i in idents):
            continue
        lines = c.hit.content.split("\n")[: c.shown_end - c.shown_start + 1]
        hit_lines = [n for n, ln in enumerate(lines) if any(i.split(".")[-1] in ln for i in idents)]
        if hit_lines:
            lo, hi = c.shown_start + hit_lines[0], c.shown_start + hit_lines[-1]
            if hi - lo > 40:
                hi = lo + 40
        else:   # identifiers only appear in the chunk's symbol name: point at the chunk's first lines
            lo, hi = c.shown_start, min(c.shown_end, c.shown_start + 10)
        score = (len(hit_lines), -int(c.label[1:]))
        if best is None or score > best[0]:
            best = (score, c.label, lo, hi)
    return best[1:] if best else None
