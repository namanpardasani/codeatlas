"""Python plugin. Symbols are extracted here; import extraction is a TODO stub (see below)."""
import tree_sitter as ts
import tree_sitter_python as tsp

from .base import MAX_DEPTH, LanguagePlugin, signature, text
from .complexity import PY_RULES, measure
from .types import ParseResult, RawImport, Symbol


def _param_names(params: ts.Node | None) -> list[str]:
    if params is None:
        return []
    out: list[str] = []
    for p in params.named_children:
        t = p.type
        if t == "identifier":
            out.append(text(p))
        elif t in ("default_parameter", "typed_default_parameter"):
            out.append(text(p.child_by_field_name("name")))
        elif t == "typed_parameter":
            first = p.named_children[0] if p.named_children else None
            out.append(text(first))  # identifier, or *args / **kwargs splat pattern
        elif t in ("list_splat_pattern", "dictionary_splat_pattern"):
            out.append(("*" if t == "list_splat_pattern" else "**") + text(p.named_children[0]) if p.named_children else text(p))
        # keyword_separator (*) and positional_separator (/) are not parameters
    return out


def _has_docstring(body: ts.Node | None) -> bool:
    if body is None or not body.named_children:
        return False
    first = body.named_children[0]
    return first.type == "expression_statement" and bool(first.named_children) \
        and first.named_children[0].type == "string"


class PythonPlugin(LanguagePlugin):
    name = "python"
    extensions = (".py",)
    IMPORT_TYPES = frozenset({"import_statement", "import_from_statement", "future_import_statement"})

    def is_docstring(self, node: ts.Node) -> bool:
        if node.type != "expression_statement" or not node.named_children or node.named_children[0].type != "string":
            return False
        parent = node.parent
        if parent is None or not parent.named_children or parent.named_children[0].id != node.id:
            return False
        return parent.type == "module" or (
            parent.type == "block" and parent.parent is not None
            and parent.parent.type in ("function_definition", "class_definition"))

    def __init__(self):
        super().__init__(tsp.language())

    def extract(self, root: ts.Node, source: bytes, result: ParseResult) -> None:
        self._walk(root, None, None, result, 0)
        self._exports(root, result)
        self.extract_imports(root, source, result)

    # ---- symbols -----------------------------------------------------------
    def _walk(self, node, parent, parent_kind, result, depth):
        if depth > MAX_DEPTH:
            return
        t = node.type
        if t == "decorated_definition":
            inner = node.child_by_field_name("definition")
            if inner is not None:
                self._walk(inner, parent, parent_kind, result, depth + 1)
            return
        if t == "function_definition":
            name = text(node.child_by_field_name("name"))
            kind = "method" if parent_kind == "class" else "function"
            self._add(result, node, name, kind, parent, parent_kind,
                      _param_names(node.child_by_field_name("parameters")),
                      _has_docstring(node.child_by_field_name("body")))
            self._children(node, name, "function", result, depth)
            return
        if t == "class_definition":
            name = text(node.child_by_field_name("name"))
            self._add(result, node, name, "class", parent, parent_kind, [],
                      _has_docstring(node.child_by_field_name("body")))
            self._children(node, name, "class", result, depth)
            return
        if t == "assignment":  # f = lambda x: ...
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            if left is not None and left.type == "identifier" and right is not None and right.type == "lambda":
                self._add(result, node, text(left), "function", parent, parent_kind,
                          _param_names(right.child_by_field_name("parameters")), False)
                return
        self._children(node, parent, parent_kind, result, depth)

    def _children(self, node, parent, parent_kind, result, depth):
        for child in node.named_children:
            self._walk(child, parent, parent_kind, result, depth + 1)

    @staticmethod
    def _add(result, node, name, kind, parent, parent_kind, params, has_doc):
        if not name:
            return
        top_level = parent is None
        sym = Symbol(
            name=name, kind=kind,
            start_line=node.start_point.row + 1, end_line=node.end_point.row + 1,
            params=params, parent=parent,
            # Python convention: public top-level names are the module's exports
            is_exported=top_level and not name.startswith("_"),
            has_doc=has_doc, signature=signature(node),
        )
        n_params = len(params) - (1 if kind == "method" and params and params[0] in ("self", "cls") else 0)
        sym.param_count = n_params
        if kind in ("function", "method"):
            sym.complexity, sym.max_nesting = measure(node, PY_RULES)
        result.symbols.append(sym)

    @staticmethod
    def _exports(root, result):
        """`__all__ = [...]` wins; otherwise public top-level symbols."""
        explicit: list[str] | None = None
        for stmt in root.named_children:
            if stmt.type != "expression_statement" or not stmt.named_children:
                continue
            a = stmt.named_children[0]
            if a.type == "assignment" and text(a.child_by_field_name("left")) == "__all__":
                right = a.child_by_field_name("right")
                if right is not None and right.type in ("list", "tuple"):
                    explicit = [text(s)[1:-1] for s in right.named_children if s.type == "string"
                                and len(text(s)) >= 2]
        names = explicit if explicit is not None else [
            s.name for s in result.symbols if s.is_exported]
        result.exports.extend(names)

    # ---- imports -----------------------------------------------------------
    def extract_imports(self, root: ts.Node, source: bytes, result: ParseResult) -> None:
        """Python import extraction (implemented in python_imports.py).

        Append a RawImport to result.imports for each of:
          import os                    -> RawImport("os", "import", line, [])
          import os.path as p          -> RawImport("os.path", "import", line, [])
          from a.b import c, d as e    -> RawImport("a.b", "from", line, ["c", "d"])
          from . import x              -> RawImport("", "from", line, ["x"], level=1)
          from ..pkg import y          -> RawImport("pkg", "from", line, ["y"], level=2)
          from m import *              -> RawImport("m", "from", line, ["*"])

        Node types you will meet (see the tree dump in NOTES.md / tests):
          import_statement, import_from_statement, dotted_name, aliased_import,
          relative_import (import_prefix + optional dotted_name), wildcard_import.
        Specifiers are stored UNRESOLVED. Resolution to files is Day 3.
        """
        from .python_imports import collect_imports
        collect_imports(root, result)
