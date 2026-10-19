"""Chunking of non-code (markdown) and code in languages we do not parse: by sections."""
import re

from .. import config
from .split import paragraph_chunks
from .types import Chunk, make_header

HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def markdown_sections(lines: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, 'Title > Subtitle') per heading section; fenced code blocks are not scanned for headings."""
    heads: list[tuple[int, int, str]] = []
    fence = False
    for i, ln in enumerate(lines, 1):
        if ln.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence and (m := HEADING.match(ln)):
            heads.append((i, len(m.group(1)), m.group(2)))
    out: list[tuple[int, int, str]] = []
    first = heads[0][0] if heads else len(lines) + 1
    if first > 1 and any(x.strip() for x in lines[: first - 1]):
        out.append((1, first - 1, ""))
    stack: list[tuple[int, str]] = []
    for k, (line, level, title) in enumerate(heads):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end = (heads[k + 1][0] - 1) if k + 1 < len(heads) else len(lines)
        out.append((line, end, " > ".join(t for _, t in stack)))
    return out


def chunk_markdown(path: str, language: str | None, lines: list[str]) -> list[Chunk]:
    out: list[Chunk] = []
    for s, e, title in markdown_sections(lines):
        title = title or path.rsplit("/", 1)[-1]
        for a, b in paragraph_chunks(lines, s, e):
            body = "\n".join(lines[a - 1:b])
            if body.strip():
                out.append(Chunk(path, language, "section", title, None, a, b, body,
                                 make_header(path, "section", title), "ast"))
    return out


def chunk_generic(path: str, language: str | None, lines: list[str]) -> list[Chunk]:
    """Config files, docs, and source in languages without a parser: blank-line sections."""
    out: list[Chunk] = []
    for a, b in paragraph_chunks(lines, 1, len(lines)):
        body = "\n".join(lines[a - 1:b])
        if body.strip():
            out.append(Chunk(path, language, "section", None, None, a, b, body,
                             make_header(path, "section", None), "ast"))
    return out
