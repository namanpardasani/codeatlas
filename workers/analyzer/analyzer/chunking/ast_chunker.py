"""AST-aware chunker: one chunk per function / method / class, built from the parser's symbol ranges.

Rules (each is covered by tests/test_chunking.py):
  1. A symbol that fits in CHUNK_MAX_CHARS is ONE chunk, together with the comments / decorators / JSDoc
     directly above it.
  2. An oversized class -> a chunk for its own lines (signature, docstring, fields) + one chunk per method.
  3. An oversized function -> split at logical blank-line boundaries (shallowest indentation first) with
     CHUNK_OVERLAP_LINES overlap; each part keeps the symbol and is labelled "part i/N".
  4. Code between symbols (imports, constants, scripts) -> `module` chunks, split by paragraphs.
  5. Tiny neighbours with the same parent and only blank lines between them are merged into a `group`.
"""
from dataclasses import dataclass, field

from .. import config
from ..parsing.types import Symbol
from .split import paragraph_chunks, split_lines
from .types import Chunk, make_header

CODE_KINDS = {"function", "method", "class", "interface", "type", "enum"}
ATTACH_PREFIXES = ("@", "#", "//", "/*", "*")  # decorators and comments directly above a symbol


@dataclass
class Node:
    sym: Symbol
    start: int
    end: int
    children: list["Node"] = field(default_factory=list)


def _build_tree(symbols: list[Symbol]) -> list[Node]:
    nodes = sorted((Node(s, s.start_line, s.end_line) for s in symbols if s.kind in CODE_KINDS),
                   key=lambda n: (n.start, -n.end))
    roots: list[Node] = []
    stack: list[Node] = []
    for n in nodes:
        while stack and not (n.start >= stack[-1].start and n.end <= stack[-1].end):
            stack.pop()
        if stack:
            if (n.start, n.end) == (stack[-1].start, stack[-1].end):
                continue  # duplicate of its parent's range
            stack[-1].children.append(n)
        else:
            if roots and n.start <= roots[-1].end:  # partial overlap: keep the earlier one intact
                n.start = roots[-1].end + 1
                if n.start > n.end:
                    continue
            roots.append(n)
        stack.append(n)
    return roots


def _attach_leading(nodes: list[Node], lines: list[str], floor: int) -> None:
    """Pull comment / decorator lines directly above a symbol into it; recurse into children."""
    prev_end = floor - 1
    for n in nodes:
        s = n.start
        while s - 1 > prev_end and lines[s - 2].strip() and lines[s - 2].lstrip().startswith(ATTACH_PREFIXES):
            s -= 1
        n.start = s
        _attach_leading(n.children, lines, n.start + 1)
        prev_end = n.end


def _trim(lines: list[str], a: int, b: int) -> tuple[int, int] | None:
    while a <= b and not lines[a - 1].strip():
        a += 1
    while b >= a and not lines[b - 1].strip():
        b -= 1
    return (a, b) if a <= b else None


def _uncovered(start: int, end: int, covered: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out, cur = [], start
    for a, b in sorted(covered):
        if a > cur:
            out.append((cur, a - 1))
        cur = max(cur, b + 1)
    if cur <= end:
        out.append((cur, end))
    return out


def chunk_ast(path: str, language: str | None, text: str, symbols: list[Symbol]) -> list[Chunk]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return []
    max_chars = config.CHUNK_MAX_CHARS
    roots = _build_tree(symbols)
    _attach_leading(roots, lines, 1)
    out: list[Chunk] = []

    def seg(a: int, b: int) -> str:
        return "\n".join(lines[a - 1:b])

    def add(kind, symbol, parent, a, b, part=None):
        body = seg(a, b)
        if body.strip():
            out.append(Chunk(path, language, kind, symbol, parent, a, b, body, make_header(path, kind, symbol, part), "ast"))

    def add_range(kind, symbol, parent, a, b):
        """A line range that may need splitting."""
        t = _trim(lines, a, b)
        if not t:
            return
        a, b = t
        if len(seg(a, b)) <= max_chars:
            add(kind, symbol, parent, a, b)
        else:
            parts = split_lines(lines, a, b)
            for i, (pa, pb) in enumerate(parts, 1):
                add(kind, symbol, parent, pa, pb, (i, len(parts)))

    def emit(node: Node, prefix: str | None):
        qual = f"{prefix}.{node.sym.name}" if prefix else node.sym.name
        kind = node.sym.kind
        if len(seg(node.start, node.end)) <= max_chars:
            add(kind, qual, prefix, node.start, node.end)
        elif node.children and kind == "class":
            for a, b in _uncovered(node.start, node.end, [(c.start, c.end) for c in node.children]):
                add_range("class", qual, prefix, a, b)
            for c in node.children:
                emit(c, qual)
        else:
            add_range(kind, qual, prefix, node.start, node.end)

    for r in roots:
        emit(r, None)
    for a, b in _uncovered(1, len(lines), [(r.start, r.end) for r in roots]):
        t = _trim(lines, a, b)
        if not t:
            continue
        for pa, pb in paragraph_chunks(lines, t[0], t[1]):
            add("module", None, None, pa, pb)

    out.sort(key=lambda c: (c.start_line, c.end_line))
    return _merge_small(out, lines, path, language)


def _merge_small(chunks: list[Chunk], lines: list[str], path: str, language: str | None) -> list[Chunk]:
    merged: list[Chunk] = []
    for c in chunks:
        if merged and _mergeable(merged[-1], c, lines):
            a = merged.pop()
            kind = a.kind if a.kind == c.kind and a.kind in ("module", "group") else "group"
            names = [n for n in dict.fromkeys(filter(None, [*(a.symbol or "").split(", "), c.symbol])) if n]
            symbol = ", ".join(names[:3]) + ("…" if len(names) > 3 else "") if names else None
            body = "\n".join(lines[a.start_line - 1:c.end_line])
            merged.append(Chunk(path, language, kind, symbol, a.parent, a.start_line, c.end_line, body,
                                make_header(path, kind, symbol), "ast"))
        else:
            merged.append(c)
    return merged


def _mergeable(a: Chunk, b: Chunk, lines: list[str]) -> bool:
    if a.parent != b.parent or "[part " in a.header or "[part " in b.header:
        return False
    if a.end_line >= b.start_line or any(x.strip() for x in lines[a.end_line:b.start_line - 1]):
        return False  # not adjacent (code in between)
    la, lb = len(a.content), len(b.content)
    span = sum(len(x) + 1 for x in lines[a.start_line - 1:b.end_line])
    return span <= config.CHUNK_MAX_CHARS and ((la < config.CHUNK_MIN_CHARS and lb < config.CHUNK_MIN_CHARS)
                                               or min(la, lb) < config.CHUNK_TINY_CHARS)
