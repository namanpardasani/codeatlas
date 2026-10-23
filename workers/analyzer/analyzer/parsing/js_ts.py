"""TypeScript / TSX / JavaScript (incl. JSX) plugin. Walks the tree for symbols and imports."""
import tree_sitter as ts
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tst

from .base import MAX_DEPTH, LanguagePlugin, signature, text
from .complexity import JS_RULES, measure
from .types import CallSite, ParseResult, RawImport, Symbol, TestCase, VarType

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


def _dotted(node: ts.Node | None) -> str | None:
    """`a`, `this.x`, `a.b.c` when the expression is a plain chain of names; else None."""
    if node is None:
        return None
    if node.type in ("identifier", "this", "super", "type_identifier", "property_identifier"):
        return text(node)
    if node.type in ("member_expression", "nested_type_identifier", "nested_identifier"):
        obj = node.child_by_field_name("object") or (node.named_children[0] if node.named_children else None)
        prop = node.child_by_field_name("property") or node.child_by_field_name("name") or (
            node.named_children[-1] if node.named_children else None)
        base = _dotted(obj)
        return f"{base}.{text(prop)}" if base is not None and prop is not None and prop.id != obj.id else None
    return None


def _split(node: ts.Node | None) -> tuple[str | None, str]:
    """(qualifier, name) of a callee: `f` -> (None, "f"); `a.b.f` -> ("a.b", "f"); unnamed -> (None, "")."""
    d = _dotted(node)
    if d is None:
        return None, ""
    q, _, name = d.rpartition(".")
    return (q or None), name


def _call_site(fn: ts.Node | None, line: int) -> CallSite | None:
    if fn is None:
        return CallSite("", None, line, "dynamic")
    if fn.type == "import":                       # import('./x') is an import, recorded elsewhere
        return None
    if fn.type == "identifier" and text(fn) == "require":
        return None
    if fn.type == "super":                        # super(...) in a constructor = the base class constructor
        return CallSite("constructor", "super", line)
    if fn.type == "member_expression":
        prop = fn.child_by_field_name("property")
        q = _dotted(fn.child_by_field_name("object"))
        if prop is None or prop.type not in ("property_identifier", "private_property_identifier"):
            return CallSite("", None, line, "dynamic")
        return CallSite(text(prop), q if q is not None else "<expr>", line)
    if fn.type == "identifier":
        return CallSite(text(fn), None, line)
    return CallSite("", None, line, "dynamic")    # obj[k](), f()(), (a || b)()


TEST_FNS = {"it": "test", "test": "test", "specify": "test", "describe": "suite", "suite": "suite", "context": "suite"}


def _test_case(call: ts.Node) -> TestCase | None:
    """it("adds", ...), test.only("x", ...), describe.each(rows)("x %s", ...) -> TestCase; anything else -> None."""
    fn = call.child_by_field_name("function")
    root = fn
    while root is not None and root.type in ("member_expression", "call_expression"):
        root = root.child_by_field_name("object") if root.type == "member_expression" else root.child_by_field_name("function")
    if root is None or root.type != "identifier" or text(root) not in TEST_FNS:
        return None
    args = call.child_by_field_name("arguments")
    first = args.named_children[0] if args is not None and args.named_children else None
    if first is None or first.type not in ("string", "template_string"):
        return None
    if not any(a.type in FUNCTION_VALUES for a in args.named_children[1:]):
        return None                                   # it("todo") without a body is not a runnable test
    name = text(first)[1:-1]
    return TestCase(name, TEST_FNS[text(root)], call.start_point.row + 1, call.end_point.row + 1)


def _type_name(node: ts.Node | None) -> str | None:
    if node is None:
        return None
    if node.type in ("type_identifier", "nested_type_identifier", "identifier", "member_expression"):
        return _dotted(node)
    return None                                   # generics, unions, literal types: no single class


def _annotated(node: ts.Node) -> str | None:
    ann = node.child_by_field_name("type") or next((c for c in node.named_children if c.type == "type_annotation"), None)
    if ann is not None and ann.type == "type_annotation":
        ann = ann.named_children[0] if ann.named_children else None
    return _type_name(ann)


def _new_type(value: ts.Node | None) -> str | None:
    if value is not None and value.type == "new_expression":
        return _type_name(value.child_by_field_name("constructor"))
    return None


def _bases(cls: ts.Node) -> list[str]:
    out: list[str] = []
    for c in cls.named_children:
        if c.type == "class_heritage":
            for clause in c.named_children:
                if clause.type == "extends_clause":
                    out += [b for b in (_dotted(v) for v in clause.named_children) if b]
                elif clause.type not in ("implements_clause",):   # JS grammar: class_heritage holds the expression
                    b = _dotted(clause)
                    if b:
                        out.append(b)
    return out


def _wrapped_function(value: ts.Node) -> ts.Node | None:
    """The function passed to a wrapper call (memo(fn), forwardRef(fn), $constructor("X", fn), asyncHandler(fn)), or
    None. Only direct arguments count, so `const x = compute(a)` stays a plain value."""
    if value.type == "await_expression" and value.named_children:
        value = value.named_children[0]
    if value.type != "call_expression":
        return None
    args = value.child_by_field_name("arguments")
    if args is None:
        return None
    return next((a for a in args.named_children if a.type in FUNCTION_VALUES), None)


def _require_bindings(call: ts.Node) -> list[tuple[str, str]]:
    """const x = require('m') -> [("x", "*")]; const {a, b: c} = require('m') -> [("a", "a"), ("c", "b")]."""
    decl = call.parent
    if decl is None or decl.type != "variable_declarator":
        return []
    name = decl.child_by_field_name("name")
    if name is None:
        return []
    if name.type == "identifier":
        return [(text(name), "*")]
    if name.type == "object_pattern":
        out = []
        for p in name.named_children:
            if p.type == "shorthand_property_identifier_pattern":
                out.append((text(p), text(p)))
            elif p.type == "pair_pattern":
                k, v = p.child_by_field_name("key"), p.child_by_field_name("value")
                if k is not None and v is not None and v.type == "identifier":
                    out.append((text(v), text(k)))
        return out
    return []


class JsTsPlugin(LanguagePlugin):
    IMPORT_TYPES = frozenset({"import_statement"})

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
        sym.param_count = len(sym.params)
        if kind in ("function", "method"):
            sym.complexity, sym.max_nesting = measure(node, JS_RULES)
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
                self._add(result, node, name, "class", parent, None, exported, default, doc_node).bases = _bases(node)
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
                    self._add(result, decl, name, "class", parent, None, exported, default,
                              doc_node or node).bases = _bases(value)
                    self._class_body(value, name, result, pending, depth)
                elif value.type in ("call_expression", "await_expression") and _wrapped_function(value) is not None:
                    # const Comp = memo(() => ...); const ZodX = $constructor("X", (inst) => {...}): the wrapped
                    # function IS this declaration's code, so calls inside it belong to `name`
                    fn = _wrapped_function(value)
                    self._add(result, decl, name, "function", parent, _param_names(
                        fn.child_by_field_name("parameters") or fn.child_by_field_name("parameter")),
                        exported, default, doc_node or node)
                    self._recurse(value, name, result, pending, depth)
                else:   # objects, `module.exports = function`, other values: look inside
                    self._walk_symbols(value, parent, result, pending, depth + 1)
            return

        elif t in ("function_expression", "function") and node.child_by_field_name("name") is not None:
            # a named function expression anywhere else: `cond && function httpAdapter(c) {...}`, callbacks
            name = text(node.child_by_field_name("name"))
            self._add(result, node, name, "function", parent, _param_names(node.child_by_field_name("parameters")))
            self._recurse(node, name, result, pending, depth)
            return
        elif t == "assignment_expression" and self._assigned_function(node, parent, result, pending, depth):
            return
        elif t == "object":
            self._object_methods(node, parent, result, pending, depth)
            return

        self._recurse(node, parent, result, pending, depth)

    def _assigned_function(self, node, parent, result, pending, depth) -> bool:
        """CommonJS / prototype style: exports.f = function () {}, module.exports = function f() {},
        Foo.prototype.bar = function () {}, app.use = function use() {}. Returns True when handled."""
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        chain = _dotted(left)
        if chain is None or right is None:
            return False
        if chain == "module.exports":
            if right.type == "identifier":
                result.export_aliases.append(("default", text(right)))
                result.exports.append("default")
                return False
            if right.type in FUNCTION_VALUES or right.type in CLASS_VALUES:
                own = right.child_by_field_name("name")
                name = text(own) if own is not None else "default"
                kind = "class" if right.type in CLASS_VALUES else "function"
                sym = self._add(result, right, name, kind, None, None if kind == "class" else _param_names(
                    right.child_by_field_name("parameters") or right.child_by_field_name("parameter")), True, True, node)
                if name != "default":
                    result.export_aliases.append(("default", name))
                if kind == "class":
                    sym.bases = _bases(right)
                    self._class_body(right, name, result, pending, depth)
                else:
                    self._recurse(right, name, result, pending, depth)
                return True
            return False
        if right.type not in FUNCTION_VALUES or "." not in chain:
            return False
        owner, _, name = chain.rpartition(".")
        params = _param_names(right.child_by_field_name("parameters") or right.child_by_field_name("parameter"))
        if owner in ("exports", "module.exports"):
            self._add(result, right, name, "function", None, params, True, False, node)
        else:
            cls = owner[: -len(".prototype")] if owner.endswith(".prototype") else owner
            self._add(result, right, name, "method", cls.rsplit(".", 1)[-1], params, doc_node=node)
        self._recurse(right, name, result, pending, depth)
        return True

    def _object_methods(self, obj, parent, result, pending, depth):
        """Methods of an object literal ({ read(k) {...}, write: function () {...}, run: () => ... }) become
        methods whose parent is the variable holding the object (or the enclosing symbol)."""
        holder = parent
        decl = obj.parent
        if decl is not None and decl.type == "variable_declarator" and decl.child_by_field_name("name") is not None:
            holder = text(decl.child_by_field_name("name"))
        elif decl is not None and decl.type == "export_statement":
            holder = "default"
        for member in obj.named_children:
            if member.type == "method_definition":
                mname = text(member.child_by_field_name("name"))
                if mname and holder:
                    self._add(result, member, mname, "method", holder, _param_names(member.child_by_field_name("parameters")))
                    self._recurse(member, mname, result, pending, depth + 1)
                    continue
            elif member.type == "pair":
                key, value = member.child_by_field_name("key"), member.child_by_field_name("value")
                if holder and key is not None and key.type in ("property_identifier", "string") and value is not None \
                        and value.type in FUNCTION_VALUES:
                    kname = text(key).strip("'\"")
                    self._add(result, value, kname, "method", holder,
                              _param_names(value.child_by_field_name("parameters") or value.child_by_field_name("parameter")))
                    self._recurse(value, kname, result, pending, depth + 1)
                    continue
            self._walk_symbols(member, parent, result, pending, depth + 1)

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
            # bindings of a re-export = names this module now exports: (exported, name in the source module)
            spec_pairs = [(alias, local) for local, alias in self._export_specifiers(node)]
            ns = next((c for c in node.named_children if c.type == "namespace_export"), None)
            if ns is not None:
                ident = next((g for g in ns.named_children if g.type in ("identifier", "string")), None)
                spec_pairs = [(text(ident).strip("'\""), "*")] if ident is not None else [("*", "*")]
            result.imports.append(RawImport(
                specifier=source, kind="reexport", line=node.start_point.row + 1,
                names=names, is_type_only=any(c.type == "type" for c in node.children),
                bindings=spec_pairs or [("*", "*")]))
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
                self._add(result, value, "default", "class", parent, None, True, True, node).bases = _bases(value)
                self._class_body(value, "default", result, pending, depth)
            elif value.type == "identifier":
                pending.append((text(value), True))
                result.exports.append("default")
                result.export_aliases.append(("default", text(value)))
            else:
                result.exports.append("default")
                self._walk_symbols(value, parent, result, pending, depth + 1)
            return
        # export { a, b as c }
        for local, exported_name in self._export_specifiers(node):
            pending.append((local, False))
            result.exports.append(exported_name)
            if local != exported_name:
                result.export_aliases.append((exported_name, local))

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
                    result.imports.append(RawImport(spec, "require", node.start_point.row + 1,
                                                    bindings=_require_bindings(node)))
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
                    result.imports.append(RawImport(spec, "require", line, names, bindings=[(n, "*") for n in names]))
                return
        spec = _string_value(node.child_by_field_name("source"))
        if spec is None:
            return
        names: list[str] = []
        bindings: list[tuple[str, str]] = []
        for c in node.named_children:
            if c.type != "import_clause":
                continue
            for part in c.named_children:
                if part.type == "identifier":
                    names.append("default")
                    bindings.append((text(part), "default"))
                elif part.type == "namespace_import":
                    names.append("*")
                    ident = next((g for g in part.named_children if g.type == "identifier"), None)
                    if ident is not None:
                        bindings.append((text(ident), "*"))
                elif part.type == "named_imports":
                    for spec_node in part.named_children:
                        if spec_node.type == "import_specifier":
                            name = text(spec_node.child_by_field_name("name"))
                            alias = spec_node.child_by_field_name("alias")
                            names.append(name)
                            bindings.append((text(alias) if alias is not None else name, name))
        result.imports.append(RawImport(spec, "import", line, names, is_type_only=type_only, bindings=bindings))

    # ---- calls + type hints -------------------------------------------------
    def extract_calls(self, root: ts.Node, result: ParseResult) -> None:
        stack = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            if depth > MAX_DEPTH:
                continue
            t = node.type
            line = node.start_point.row + 1
            if t == "call_expression":
                site = _call_site(node.child_by_field_name("function"), line)
                if site is not None:
                    result.calls.append(site)
                tc = _test_case(node)
                if tc is not None:
                    result.tests.append(tc)
            elif t == "new_expression":
                ctor = node.child_by_field_name("constructor")
                q, name = _split(ctor)
                result.calls.append(CallSite(name, q, line, "new") if name else CallSite("", None, line, "dynamic"))
            elif t in ("jsx_opening_element", "jsx_self_closing_element"):
                q, name = _split(node.child_by_field_name("name"))
                if name and (q is not None or name[:1].isupper()):     # <div> is a DOM tag, <Foo> a component
                    result.calls.append(CallSite(name, q, line, "jsx"))
            elif t == "variable_declarator":
                nm = node.child_by_field_name("name")
                if nm is not None and nm.type == "identifier":
                    ty = _annotated(node) or _new_type(node.child_by_field_name("value"))
                    if ty:
                        result.var_types.append(VarType(text(nm), ty, line))
            elif t == "assignment_expression":
                left = _dotted(node.child_by_field_name("left"))
                ty = _new_type(node.child_by_field_name("right"))
                if left and ty:
                    result.var_types.append(VarType(left, ty, line))
            elif t in ("public_field_definition", "field_definition"):
                nm = node.child_by_field_name("name") or node.child_by_field_name("property")
                ty = _annotated(node) or _new_type(node.child_by_field_name("value"))
                if nm is not None and ty:
                    result.var_types.append(VarType(f"this.{text(nm)}", ty, line))
            elif t in ("required_parameter", "optional_parameter"):
                pat = node.child_by_field_name("pattern")
                ty = _annotated(node)
                if pat is not None and pat.type == "identifier" and ty:
                    result.var_types.append(VarType(text(pat), ty, line))
                    if any(c.type == "accessibility_modifier" for c in node.children):   # constructor(private s: Svc)
                        result.var_types.append(VarType(f"this.{text(pat)}", ty, line))
            stack.extend((c, depth + 1) for c in reversed(node.named_children))


def make_plugins() -> list[JsTsPlugin]:
    return [
        JsTsPlugin("typescript", (".ts", ".mts", ".cts"), tst.language_typescript()),
        JsTsPlugin("tsx", (".tsx",), tst.language_tsx()),
        JsTsPlugin("javascript", (".js", ".jsx", ".mjs", ".cjs"), tsjs.language()),
    ]
