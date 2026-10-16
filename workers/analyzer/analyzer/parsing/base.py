from abc import ABC, abstractmethod

import tree_sitter as ts

from .types import ParseResult

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
        # deterministic output regardless of traversal order
        result.symbols.sort(key=lambda s: (s.start_line, s.end_line, s.name, s.kind))
        result.imports.sort(key=lambda i: (i.line, i.specifier, i.kind))
        result.exports = sorted(set(result.exports))
        return result

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
