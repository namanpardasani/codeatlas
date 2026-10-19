"""Identifier-aware text helpers for keyword search."""
import re

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
STOPWORDS = frozenset("""a an and are as at be by do does for from how i if in into is it of on or that the this to was
what when where which who why with without""".split())
MAX_EXTRA_WORDS = 4000


def split_identifier(name: str) -> list[str]:
    """getUserName -> [get, user, name]; parse_HTTPResponse2 -> [parse, http, response, 2]."""
    return [w.lower() for part in name.split("_") if part for w in _CAMEL.findall(part)]


def expand_identifiers(text: str) -> str:
    """text + the sub-words of every identifier in it, so `getUserName` is findable as "get user name".
    The 'simple' tsvector config keeps camelCase tokens whole; this restores the word-level matches."""
    extra: dict[str, None] = {}
    for ident in IDENT.findall(text):
        if len(ident) > 2 and (("_" in ident) or ident != ident.lower()):
            for w in split_identifier(ident):
                extra[w] = None
                if len(extra) >= MAX_EXTRA_WORDS:
                    break
    return text + "\n" + " ".join(extra)


def query_terms(query: str) -> list[str]:
    """Search terms from a natural-language or identifier query: lowercase words, identifiers split
    AND kept whole, stop words dropped, order preserved, duplicates removed."""
    terms: dict[str, None] = {}
    for ident in IDENT.findall(query) or re.findall(r"[A-Za-z0-9]+", query):
        low = ident.lower()
        words = split_identifier(ident)
        if low not in STOPWORDS and len(low) > 1:
            terms[low.replace("_", "")] = None   # the identifier kept whole (matches camelCase tokens)
        for w in words:
            if w not in STOPWORDS and len(w) > 1:
                terms[w] = None
    return [t for t in terms if t]


def to_tsquery(terms: list[str]) -> str:
    """OR-query for to_tsquery('simple', ...): any term matches; ts_rank_cd ranks by how many/how close."""
    safe = [re.sub(r"[^a-z0-9]", "", t) for t in terms]
    return " | ".join(t for t in safe if t)
