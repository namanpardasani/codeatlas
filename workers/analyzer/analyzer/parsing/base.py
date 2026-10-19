from abc import ABC, abstractmethod

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
        result.symbols.sort(key=lambda s: (s.start_line, s.end_line, s.name, s.kind))
        result.imports.sort(key=lambda i: (i.line, i.specifier, i.kind))
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

    @abstractmethod
    def extract(self, root: ts.Node, source: bytes, result: ParseResult) -> None: ...


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
