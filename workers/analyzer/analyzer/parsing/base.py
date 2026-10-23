import hashlib
from abc import ABC, abstractmethod
from bisect import bisect_left, bisect_right

import zlib

import tree_sitter as ts

from .types import FileMetrics, ParseResult

MAX_DEPTH = 120  # guard against pathologically nested input (recursion limit)
SIGNATURE_MAX = 200


class LanguagePlugin(ABC):
    """One plugin per language. Adding a language = one subclass + a registry entry."""

    name: str
    extensions: tuple[str, ...]

    def __init__(self, language_capsule):
        self._parser = ts.Parser(ts.Language(language_capsule))

    def parse(self, source: bytes) -> ParseResult:
        tree = self._parser.parse(source)
        root = tree.root_node
        result = ParseResult()
        if root.has_error:
            result.status = "partial"
            result.error = first_error(root)
        self.extract(root, source, result)
        self.scan(root, source, result)
        # deterministic output regardless of traversal order
        self.extract_calls(root, result)
        result.symbols.sort(key=lambda s: (s.start_line, s.end_line, s.name, s.kind))
        result.imports.sort(key=lambda i: (i.line, i.specifier, i.kind))
        result.calls.sort(key=lambda c: (c.line, c.qualifier or "", c.callee, c.kind))
        result.var_types.sort(key=lambda v: (v.line, v.name, v.type_name))
        result.exports = sorted(set(result.exports))
        return result

    COMMENT_TYPES: frozenset = frozenset({"comment"})
    IMPORT_TYPES: frozenset = frozenset()  # excluded from duplicate detection (imports repeat everywhere)

    def is_docstring(self, node: ts.Node) -> bool:
        return False

    def scan(self, root: ts.Node, source: bytes, result: ParseResult) -> None:
        """One pass over the tree: line metrics (comments vs code) and the normalized token stream."""
        comment_rows: set[int] = set()
        code_rows: set[int] = set()
        hashes: list[int] = []
        lines: list[int] = []
        leaf_rows: list[int] = []      # code leaves in source order, for symbol body fingerprints
        leaf_texts: list[bytes] = []
        import_rows: set[int] = set()  # rows holding import statements
        crc: dict[str, int] = {}
        stack = [root]
        while stack:
            n = stack.pop()
            t = n.type
            if t in self.COMMENT_TYPES or self.is_docstring(n):
                comment_rows.update(range(n.start_point.row, n.end_point.row + 1))
                continue
            if t in self.IMPORT_TYPES:
                code_rows.update(range(n.start_point.row, n.end_point.row + 1))
                import_rows.update(range(n.start_point.row, n.end_point.row + 1))
                leaf_rows.append(n.start_point.row)
                leaf_texts.append(b" ".join(source[n.start_byte:n.end_byte].split()))
                continue
            if n.child_count == 0:
                if n.is_missing:
                    continue
                code_rows.update(range(n.start_point.row, n.end_point.row + 1))
                h = crc.get(t)
                if h is None:
                    h = crc[t] = zlib.crc32(t.encode())
                hashes.append(h)
                lines.append(n.start_point.row + 1)
                if t != ";":  # optional in JS/TS (ASI): `return x` and `return x;` are the same code
                    leaf_rows.append(n.start_point.row)
                    leaf_texts.append(source[n.start_byte:n.end_byte])
                continue
            stack.extend(reversed(n.children))

        src_lines = source.decode("utf8", errors="replace").split("\n")
        if src_lines and src_lines[-1] == "":
            src_lines.pop()
        blank_rows = {i for i, ln in enumerate(src_lines) if not ln.strip()}
        pure_comment = {r for r in comment_rows if r not in code_rows and r not in blank_rows}
        non_blank = len(src_lines) - len(blank_rows)
        result.metrics = FileMetrics(
            lines=len(src_lines), blank_lines=len(blank_rows), comment_lines=len(pure_comment),
            code_lines=non_blank - len(pure_comment),
            comment_ratio=round(len(pure_comment) / non_blank, 4) if non_blank else 0.0,
        )
        result.token_hashes, result.token_lines = hashes, lines
        set_body_hashes(result.symbols, leaf_rows, leaf_texts)
        result.module_hash = module_hash(result.symbols, leaf_rows, leaf_texts)
        keep = [i for i, r in enumerate(leaf_rows) if r not in import_rows]
        result.module_code_hash = module_hash(result.symbols, [leaf_rows[i] for i in keep], [leaf_texts[i] for i in keep])

    @abstractmethod
    def extract(self, root: ts.Node, source: bytes, result: ParseResult) -> None: ...

    def extract_calls(self, root: ts.Node, result: ParseResult) -> None:
        """Call sites and simple type hints (optional per language)."""


def set_body_hashes(symbols, leaf_rows: list[int], leaf_texts: list[bytes]) -> None:
    """body_hash = sha1 of the code leaves on the symbol's lines (0-based rows start_line-1 .. end_line-1), joined with a
    separator so `ab` + `c` never equals `a` + `bc`. Leaves arrive in source order, so their rows are sorted."""
    for s in symbols:
        lo = bisect_left(leaf_rows, s.start_line - 1)
        hi = bisect_right(leaf_rows, s.end_line - 1)
        h = hashlib.sha1(b"\x00".join(leaf_texts[lo:hi]))
        s.body_hash = h.hexdigest()[:16]


def module_hash(symbols, leaf_rows: list[int], leaf_texts: list[bytes]) -> str:
    """sha1 of the code leaves NOT inside any top-level symbol: imports, constants, module-level statements."""
    merged: list[list[int]] = []
    for a, b in sorted((s.start_line - 1, s.end_line - 1) for s in symbols if s.parent is None):
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out: list[bytes] = []
    j = 0
    for row, txt in zip(leaf_rows, leaf_texts):
        while j < len(merged) and merged[j][1] < row:
            j += 1
        if not (j < len(merged) and merged[j][0] <= row <= merged[j][1]):
            out.append(txt)
    return hashlib.sha1(b"\x00".join(out)).hexdigest()[:16]


def first_error(root: ts.Node) -> str:
    """Describe the first syntax error so the UI can show where parsing went wrong."""
    stack = [root]
    best = None
    while stack:
        n = stack.pop()
        if n.is_error or n.is_missing:
            line = n.start_point.row + 1
            if best is None or line < best:
                best = line
        if n.has_error:
            stack.extend(n.children)
    return f"syntax error near line {best}" if best else "syntax error"


def text(node: ts.Node | None) -> str:
    return node.text.decode("utf8", errors="replace") if node is not None else ""


def signature(node: ts.Node) -> str:
    line = text(node).split("\n", 1)[0].strip()
    return line[:SIGNATURE_MAX]
