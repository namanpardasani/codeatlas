"""TypeScript / TSX / JavaScript (incl. JSX) plugin. Walks the tree for symbols and imports."""
import tree_sitter as ts
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tst

from .base import MAX_DEPTH, LanguagePlugin, signature, text
from .types import ParseResult, RawImport, Symbol

FUNCTION_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
CLASS_VALUES = {"class", "class_expression"}
FUNCTION_DECLS = {"function_declaration", "generator_function_declaration"}
CLASS_DECLS = {"class_declaration", "abstract_class_declaration"}
TS_TYPE_DECLS = {
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}


def _string_value(node: ts.Node | None) -> str | None:
    """Value of a plain string literal node, else None (templates/expressions are skipped)."""
    if node is None or node.type != "string":
        return None
    raw = text(node)
    return raw[1:-1] if len(raw) >= 2 and raw[0] in "'\"" else None


def _param_names(params: ts.Node | None) -> list[str]:
    if params is None:
        return []
    if params.type == "identifier":  # `x => ...`
        return [text(params)]
    out: list[str] = []
    for p in params.named_children:
        if p.type == "comment":
            continue
        if p.type in ("required_parameter", "optional_parameter"):
            pat = p.child_by_field_name("pattern")
            out.append(text(pat) if pat is not None else text(p))
        elif p.type == "assignment_pattern":
            out.append(text(p.child_by_field_name("left")))
        else:
            out.append(text(p))
    return out


def _has_jsdoc(node: ts.Node) -> bool:
    prev = node.prev_named_sibling
    return (
        prev is not None
        and prev.type == "comment"
        and text(prev).startswith("/**")
        and prev.end_point.row >= node.start_point.row - 1
    )


class JsTsPlugin(LanguagePlugin):
    def __init__(self, name: str, extensions: tuple[str, ...], language_capsule):
        self.name = name
        self.extensions = extensions
        super().__init__(language_capsule)

    # ---- symbols + exports -------------------------------------------------
    def extract(self, root: ts.Node, source: bytes, result: ParseResult) -> None:
        pending_exports: list[tuple[str, bool]] = []  # (local name, is_default)
        self._walk_symbols(root, None, result, pending_exports, 0)
        self._apply_pending_exports(result, pending_exports)
        self._walk_imports(root, result, 0)

    def _add(self, result, node, name, kind, parent, params=None, exported=False,
             default=False, doc_node=None) -> Symbol:
        sym = Symbol(
            name=name, kind=kind,
            start_line=node.start_point.row + 1, end_line=node.end_point.row + 1,
            params=params or [], parent=parent,
            is_exported=exported, is_default_export=default,
            has_doc=_has_jsdoc(doc_node or node), signature=signature(node),
        )
        result.symbols.append(sym)
        if exported:
            result.exports.append("default" if default else name)
        return sym

    def _walk_symbols(self, node, parent, result, pending, depth, exported=False,
                      default=False, doc_node=None):
        if depth > MAX_DEPTH:
            return
        t = node.type

        if t == "export_statement":
            self._export_statement(node, parent, result, pending, depth)
            return

        if t in FUNCTION_DECLS:
            name = text(node.child_by_field_name("name"))
            if name:
                self._add(result, node, name, "function", parent,
                          _param_names(node.child_by_field_name("parameters")), exported, default, doc_node)
                self._recurse(node, name, result, pending, depth)
                return
        elif t in CLASS_DECLS:
            name = text(node.child_by_field_name("name"))
            if name:
                self._add(result, node, name, "class", parent, None, exported, default, doc_node)
                self._class_body(node, name, result, pending, depth)
                return
        elif t in TS_TYPE_DECLS:
            name = text(node.child_by_field_name("name"))
            if name:
                self._add(result, node, name, TS_TYPE_DECLS[t], parent, None, exported, default, doc_node)
                return
        elif t in ("lexical_declaration", "variable_declaration"):
            for decl in node.named_children:
                if decl.type != "variable_declarator":
                    continue
                name_node = decl.child_by_field_name("name")
                value = decl.child_by_field_name("value")
                if name_node is None or name_node.type != "identifier" or value is None:
                    continue
                name = text(name_node)
                if value.type in FUNCTION_VALUES:
                    params = _param_names(value.child_by_field_name("parameters")
                                          or value.child_by_field_name("parameter"))
                    sym = self._add(result, decl, name, "function", parent, params, exported, default,
                                    doc_node or node)
                    self._recurse(value, name, result, pending, depth)
                elif value.type in CLASS_VALUES:
                    self._add(result, decl, name, "class", parent, None, exported, default, doc_node or node)
                    self._class_body(value, name, result, pending, depth)
            return

        self._recurse(node, parent, result, pending, depth)

    def _recurse(self, node, parent, result, pending, depth):
        for child in node.named_children:
            self._walk_symbols(child, parent, result, pending, depth + 1)

    def _class_body(self, cls, name, result, pending, depth):
        body = cls.child_by_field_name("body")
        if body is None:
            return
        for member in body.named_children:
            if member.type == "method_definition":
                mname = text(member.child_by_field_name("name"))
                if mname:
                    self._add(result, member, mname, "method", name,
                              _param_names(member.child_by_field_name("parameters")))
                    self._recurse(member, mname, result, pending, depth + 1)
            elif member.type in ("public_field_definition", "field_definition"):
                value = member.child_by_field_name("value")
                nm = member.child_by_field_name("name") or member.child_by_field_name("property")
                if value is not None and value.type in FUNCTION_VALUES and nm is not None:
                    self._add(result, member, text(nm), "method", name,
                              _param_names(value.child_by_field_name("parameters")
                                           or value.child_by_field_name("parameter")))

    def _export_statement(self, node, parent, result, pending, depth):
        is_default = any(c.type == "default" for c in node.children)
        source = _string_value(node.child_by_field_name("source"))
        decl = node.child_by_field_name("declaration")
        value = node.child_by_field_name("value")

        if source is not None:  # re-export: export * from / export {a} from / export * as ns from
            names = self._export_clause_names(node) or ["*"]
            exported = [alias for _, alias in self._export_specifiers(node)] or ["*"]
            result.exports.extend(exported)
            result.imports.append(RawImport(
                specifier=source, kind="reexport", line=node.start_point.row + 1,
                names=names, is_type_only=any(c.type == "type" for c in node.children)))
            return
        if decl is not None:
            self._walk_symbols(decl, parent, result, pending, depth + 1,
                               exported=True, default=is_default, doc_node=node)
            if decl.type in ("lexical_declaration", "variable_declaration"):
                return
            return
        if value is not None and is_default:
            if value.type in FUNCTION_VALUES:
                self._add(result, value, "default", "function", parent,
                          _param_names(value.child_by_field_name("parameters")
                                       or value.child_by_field_name("parameter")),
                          True, True, node)
                self._recurse(value, "default", result, pending, depth)
            elif value.type in CLASS_VALUES:
                self._add(result, value, "default", "class", parent, None, True, True, node)
                self._class_body(value, "default", result, pending, depth)
            elif value.type == "identifier":
                pending.append((text(value), True))
                result.exports.append("default")
            else:
                result.exports.append("default")
            return
        # export { a, b as c }
        for local, exported_name in self._export_specifiers(node):
            pending.append((local, False))
            result.exports.append(exported_name)

    @staticmethod
    def _export_specifiers(node):
        for c in node.named_children:
            if c.type == "export_clause":
                for spec in c.named_children:
                    if spec.type == "export_specifier":
                        local = text(spec.child_by_field_name("name"))
                        alias = spec.child_by_field_name("alias")
                        yield local, (text(alias) if alias is not None else local)

    def _export_clause_names(self, node) -> list[str]:
        names = [local for local, _ in self._export_specifiers(node)]
        if not names and any(c.type == "*" for c in node.children):
            return ["*"]
        for c in node.named_children:
            if c.type == "namespace_export":
                return ["*"]
        return names

    @staticmethod
    def _apply_pending_exports(result, pending):
        by_name = {}
        for s in result.symbols:
            if s.parent is None:
                by_name.setdefault(s.name, s)
        for local, is_default in pending:
            sym = by_name.get(local)
            if sym:
                sym.is_exported = True
                sym.is_default_export = sym.is_default_export or is_default

    # ---- imports -----------------------------------------------------------
    def _walk_imports(self, node, result, depth):
        if depth > MAX_DEPTH:
            return
        t = node.type
        if t == "import_statement":
            self._import_statement(node, result)
        elif t == "call_expression":
            fn = node.child_by_field_name("function")
            args = node.child_by_field_name("arguments")
            first = args.named_children[0] if args is not None and args.named_children else None
            spec = _string_value(first)
            if spec is not None and fn is not None:
                if fn.type == "import":
                    result.imports.append(RawImport(spec, "dynamic", node.start_point.row + 1))
                elif fn.type == "identifier" and text(fn) == "require":
                    result.imports.append(RawImport(spec, "require", node.start_point.row + 1))
        for child in node.named_children:
            if child.type != "export_statement" or child.child_by_field_name("source") is None:
                self._walk_imports(child, result, depth + 1)

    def _import_statement(self, node, result):
        line = node.start_point.row + 1
        type_only = any(c.type == "type" for c in node.children)
        # TS: import x = require('y')
        for c in node.named_children:
            if c.type == "import_require_clause":
                spec = _string_value(next((g for g in c.named_children if g.type == "string"), None))
                if spec is not None:
                    names = [text(g) for g in c.named_children if g.type == "identifier"][:1]
                    result.imports.append(RawImport(spec, "require", line, names))
                return
        spec = _string_value(node.child_by_field_name("source"))
        if spec is None:
            return
        names: list[str] = []
        for c in node.named_children:
            if c.type != "import_clause":
                continue
            for part in c.named_children:
                if part.type == "identifier":
                    names.append("default")
                elif part.type == "namespace_import":
                    names.append("*")
                elif part.type == "named_imports":
                    for spec_node in part.named_children:
                        if spec_node.type == "import_specifier":
                            names.append(text(spec_node.child_by_field_name("name")))
        result.imports.append(RawImport(spec, "import", line, names, is_type_only=type_only))


def make_plugins() -> list[JsTsPlugin]:
    return [
        JsTsPlugin("typescript", (".ts", ".mts", ".cts"), tst.language_typescript()),
        JsTsPlugin("tsx", (".tsx",), tst.language_tsx()),
        JsTsPlugin("javascript", (".js", ".jsx", ".mjs", ".cjs"), tsjs.language()),
    ]
