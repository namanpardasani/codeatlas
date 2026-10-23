"""Function-level call graph: link every call site to the symbol it calls, with an honest confidence.

Static resolution in a dynamic language is guesswork past a point, so every edge says how it was found:

  exact     the definition is certain: same file; an explicit import (followed through re-exports); `mod.f()` on an
            imported module; `self.m()` / `this.m()` found on the enclosing class itself; `Cls.m()` on a known class.
  probable  very likely but resting on one assumption: an inherited method (found on a base class), a receiver whose
            type comes from a hint (`x = Foo()`, `s: Svc`), a name brought in by a wildcard import, `super().m()`.
  weak      name-only: a method with that name exists elsewhere in the repo and nothing more is known (`obj.save()`
            with `obj` untyped), or a global function shared between classic JS scripts. Kept only with at most
            MAX_WEAK candidates, never for names every builtin container has (get, items, push, ...), never into test
            files from library code. A bare `f()` with no import is NOT guessed: it is recorded as not_imported.

Calls that cannot be resolved are recorded with a reason (dynamic, ambiguous, import_unresolved, ...), never guessed.
Calls into packages outside the repo (and builtins) are counted as external and not stored.

Inputs are plain parse results + import resolutions, so the same code runs on an in-memory Snapshot (evaluation, PR
analysis) and inside the analysis pipeline.
"""
import builtins
import posixpath
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..parsing.types import CallSite, ParseResult, Symbol
from ..resolve.types import ImportResolution, Resolution

MAX_WEAK = 5             # name-only matches beyond this are "ambiguous": a guess spread over 6+ symbols is noise
MAX_HOPS = 8             # re-export chains / inheritance depth

PY_BUILTINS = frozenset(dir(builtins))
JS_GLOBALS = frozenset({
    "require", "setTimeout", "setInterval", "clearTimeout", "clearInterval", "setImmediate", "queueMicrotask",
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURIComponent", "decodeURIComponent", "encodeURI",
    "decodeURI", "structuredClone", "fetch", "Symbol", "Object", "Array", "String", "Number", "Boolean", "Promise",
    "Error", "TypeError", "RangeError", "SyntaxError", "Map", "Set", "WeakMap", "WeakSet", "Date", "RegExp", "JSON",
    "Math", "Reflect", "Proxy", "BigInt", "URL", "URLSearchParams", "Buffer", "AbortController", "TextEncoder",
    "TextDecoder", "alert", "atob", "btoa", "describe", "it", "test", "expect", "beforeEach", "afterEach",
    "beforeAll", "afterAll", "jest", "vi",
})
# Methods every dict/list/str/... (Python) or Array/Map/String/Promise (JS) has. With an untyped receiver,
# `d.get(k)` is far more likely a dict than the repo's one class that defines get(): no name-only guess for these.
PY_BUILTIN_METHODS = frozenset(
    n for t in (dict, list, str, set, bytes, tuple, frozenset, int, float, object, bytearray) for n in dir(t)
) | frozenset({"read", "write", "close", "seek", "tell", "flush", "readline", "readlines", "send", "recv"})
JS_BUILTIN_METHODS = frozenset({
    "push", "pop", "shift", "unshift", "slice", "splice", "concat", "join", "map", "filter", "reduce", "reduceRight",
    "forEach", "find", "findIndex", "findLast", "some", "every", "includes", "indexOf", "lastIndexOf", "sort", "reverse",
    "flat", "flatMap", "fill", "at", "keys", "values", "entries", "get", "set", "has", "delete", "clear", "add",
    "toString", "toLowerCase", "toUpperCase", "trim", "trimStart", "trimEnd", "split", "replace", "replaceAll",
    "startsWith", "endsWith", "padStart", "padEnd", "match", "matchAll", "search", "charAt", "charCodeAt", "substring",
    "substr", "repeat", "normalize", "localeCompare", "then", "catch", "finally", "call", "apply", "bind", "valueOf",
    "hasOwnProperty", "toFixed", "toISOString", "getTime", "log", "warn", "error", "info", "debug", "emit", "on",
    "once", "off", "write", "end", "next", "return", "throw", "assign", "freeze", "create", "stringify", "parse",
})
# receivers that are runtime globals in JS: Buffer.from(), Array.from(), Object.keys() are never repo methods
JS_GLOBAL_OBJECTS = frozenset({
    "Buffer", "Array", "Object", "Promise", "JSON", "Math", "console", "process", "window", "document", "globalThis",
    "Number", "String", "Date", "Reflect", "Symbol", "Intl", "navigator", "location", "history", "localStorage",
    "sessionStorage", "crypto", "performance", "URL", "Error", "RegExp", "Map", "Set", "BigInt", "Atomics",
})
TEST_PATH = ("test", "tests", "__tests__", "spec", "specs")
SELF = frozenset({"self", "this", "cls"})
CTOR = ("__init__", "constructor")


@dataclass(frozen=True, order=True)
class SymRef:
    path: str
    idx: int              # position in the file's sorted symbol list (= symbols.idx in the database)


@dataclass(frozen=True)
class CallEdge:
    caller_path: str
    caller: SymRef | None   # None = module-level code
    callee: SymRef
    confidence: str         # exact | probable | weak
    line: int
    kind: str               # call | new | jsx
    via: str                # how it was resolved (same_file, import, reexport, module_attr, self, inherited, ...)


@dataclass(frozen=True)
class Unresolved:
    path: str
    caller: SymRef | None
    callee: str
    qualifier: str | None
    line: int
    reason: str             # dynamic | ambiguous | builtin_method_name | not_imported | import_unresolved |
                            # name_not_in_module | method_not_found | base_unknown


@dataclass
class CallGraph:
    edges: list[CallEdge] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    stats: Counter = field(default_factory=Counter)      # exact / probable / weak / external / unresolved:<reason>
    symbols: dict[str, list[Symbol]] = field(default_factory=dict)
    # (importing file, symbol) for every import binding that names a symbol (`from x import F`, `import { F }`, re-exports):
    # uses that are not calls (subclassing, passing F around, re-exporting it) still depend on F
    uses: list[tuple[str, SymRef]] = field(default_factory=list)

    def callers_of(self, ref: SymRef) -> list[CallEdge]:
        return self._by_callee().get(ref, [])

    def callees_of(self, ref: SymRef) -> list[CallEdge]:
        return self._by_caller().get(ref, [])

    def _by_callee(self) -> dict[SymRef, list[CallEdge]]:
        if not hasattr(self, "_rev"):
            d: dict[SymRef, list[CallEdge]] = defaultdict(list)
            for e in self.edges:
                d[e.callee].append(e)
            self._rev = dict(d)
        return self._rev

    def _by_caller(self) -> dict[SymRef, list[CallEdge]]:
        if not hasattr(self, "_fwd"):
            d: dict[SymRef, list[CallEdge]] = defaultdict(list)
            for e in self.edges:
                if e.caller is not None:
                    d[e.caller].append(e)
            self._fwd = dict(d)
        return self._fwd

    def name(self, ref: SymRef) -> str:
        s = self.symbols[ref.path][ref.idx]
        return f"{s.parent}.{s.name}" if s.parent else s.name


# ---- per-file index ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Module:
    path: str


Target = SymRef | Module | str | None     # str: "external"; None: not found


class FileIndex:
    def __init__(self, path: str, res: ParseResult, resolutions: dict[int, Resolution]):
        self.path = path
        self.is_py = path.endswith(".py")
        self.syms = res.symbols
        self.top: dict[str, int] = {}
        self.methods: dict[tuple[str, str], int] = {}
        self.classes: dict[str, int] = {}
        # the LAST definition of a name wins (as at runtime): @overload stubs come first, the implementation last
        for i, s in enumerate(res.symbols):
            if s.parent is None:
                self.top[s.name] = i
            if s.kind == "class":
                self.classes[s.name] = i
            elif s.kind == "method" and s.parent:
                self.methods[(s.parent, s.name)] = i
        self.default_local = next((s.name for s in res.symbols if s.is_default_export and s.parent is None), None)
        self.aliases: dict[str, str] = {}
        for exported, local in res.export_aliases:
            self.aliases[exported] = local
            if exported == "default":
                self.default_local = local
        # local name -> (resolution, imported name); wildcard + star re-export targets; named re-exports
        self.bindings: dict[str, tuple[Resolution, str]] = {}
        self.wildcards: list[Resolution] = []
        self.reexports: dict[str, tuple[Resolution, str]] = {}
        self.star_reexports: list[Resolution] = []
        for i, im in enumerate(res.imports):
            r = resolutions.get(i) or Resolution("unresolved", reason="not resolved")
            for local, imported in im.bindings:
                if im.kind == "reexport":
                    if local == "*":
                        self.star_reexports.append(r)
                    else:
                        self.reexports[local] = (r, imported)
                elif local == "*":
                    self.wildcards.append(r)
                else:
                    self.bindings[local] = (r, imported)
        self.var_types = res.var_types
        # a JS file with no import/export runs as a classic script: its top-level functions are globals
        self.is_script = not self.is_py and not res.imports and not res.exports
        self.is_test = _is_test(path)

    def innermost(self, line: int, kinds: tuple[str, ...]) -> int | None:
        best = None
        for i, s in enumerate(self.syms):
            if s.kind in kinds and s.start_line <= line <= s.end_line:
                if best is None or (s.end_line - s.start_line) <= (self.syms[best].end_line - self.syms[best].start_line):
                    best = i
        return best


def _is_test(path: str) -> bool:
    from ..inventory import is_test_path
    return is_test_path(path)


def _module_name(path: str) -> str:
    base = posixpath.basename(path)
    if base in ("__init__.py", "index.js", "index.ts", "index.tsx", "index.mjs", "index.cjs", "index.jsx"):
        return posixpath.basename(posixpath.dirname(path))
    return posixpath.splitext(base)[0]


# ---- resolver ------------------------------------------------------------------------------------------------------

class Resolver:
    def __init__(self, parsed: dict[str, ParseResult], resolutions: list[ImportResolution]):
        by_file: dict[str, dict[int, Resolution]] = defaultdict(dict)
        for r in resolutions:
            by_file[r.from_path][r.idx] = r.resolution
        self.files = {p: FileIndex(p, res, by_file.get(p, {})) for p, res in parsed.items()}
        # name indexes for weak (name-only) matching
        self.top_by_name: dict[str, list[SymRef]] = defaultdict(list)
        self.methods_by_name: dict[str, list[SymRef]] = defaultdict(list)
        for p, fi in self.files.items():
            for i, s in enumerate(fi.syms):
                if s.kind == "method":
                    self.methods_by_name[s.name].append(SymRef(p, i))
                elif s.parent is None and s.kind in ("function", "class"):
                    self.top_by_name[s.name].append(SymRef(p, i))

    # -- exports of a module --
    def lookup(self, path: str, name: str, seen: frozenset = frozenset()) -> tuple[Target, str]:
        """What `name` means when imported from module `path`: (target, via). Follows re-exports, Python package
        re-exports (`from .x import y` in __init__.py), wildcard re-exports and submodules."""
        fi = self.files.get(path)
        if fi is None or (path, name) in seen or len(seen) > MAX_HOPS:
            return None, ""
        seen = seen | {(path, name)}
        if name == "*":
            return Module(path), "module"
        if not fi.is_py:
            local = fi.default_local if name == "default" else fi.aliases.get(name, name)
            if local is not None and local in fi.top:
                return SymRef(path, fi.top[local]), "import"
            if local is not None and local in fi.bindings:          # import x from './y'; export default x
                t, _ = self.resolve_binding(fi, local, seen)
                if t is not None:
                    return t, "reexport"
            if name in fi.reexports:
                r, imported = fi.reexports[name]
                return self._through(r, imported, seen, "reexport")
            if name != "default":
                for r in fi.star_reexports:
                    t, _ = self._through(r, name, seen, "reexport")
                    if isinstance(t, (SymRef, Module)):
                        return t, "reexport"
            return None, ""
        if name in fi.top:
            return SymRef(path, fi.top[name]), "import"
        if name in fi.bindings:                                      # package __init__ re-exporting a name
            t, _ = self.resolve_binding(fi, name, seen)
            if t is not None:
                return t, "reexport"
        for r in fi.wildcards:
            t, _ = self._through(r, name, seen, "reexport")
            if isinstance(t, (SymRef, Module)):
                return t, "reexport"
        if posixpath.basename(path) == "__init__.py":                # submodule of a package
            base = posixpath.dirname(path)
            for cand in (posixpath.join(base, name + ".py"), posixpath.join(base, name, "__init__.py")):
                if cand in self.files:
                    return Module(cand), "module"
        return None, ""

    def _through(self, r: Resolution, imported: str, seen: frozenset, via: str) -> tuple[Target, str]:
        if r.status == "external":
            return "external", via
        if r.status != "internal":
            return None, ""
        for target in r.targets:
            if imported == "*":
                return Module(target), "module"
            if _module_name(target) == imported and target.endswith(".py") and not target.endswith("/__init__.py") \
                    and imported not in (self.files.get(target).top if target in self.files else {}):
                return Module(target), "module"                      # from pkg import submodule
            t, v = self.lookup(target, imported, seen)
            if t is not None:
                return t, via if v == "import" else v
        return None, ""

    def resolve_binding(self, fi: FileIndex, local: str, seen: frozenset = frozenset()) -> tuple[Target, str]:
        r, imported = fi.bindings[local]
        if r.status == "external":
            return "external", "import"
        if r.status != "internal":
            return None, "import_unresolved"
        t, via = self._through(r, imported, seen, "import")
        return (t, via or "import") if t is not None else (None, "name_not_in_module")

    # -- names as seen from inside a file --
    def resolve_name(self, fi: FileIndex, dotted: str) -> tuple[Target, str]:
        """A (possibly dotted) name in file `fi`: local definition, import binding, or attribute path through
        imported modules (`pkg.mod.Cls`)."""
        if dotted in fi.top:
            return SymRef(fi.path, fi.top[dotted]), "same_file"
        if dotted in fi.bindings:
            return self.resolve_binding(fi, dotted)
        parts = dotted.split(".")
        for cut in range(len(parts) - 1, 0, -1):                     # longest bound prefix first: a.b.c, then a.b, a
            head = ".".join(parts[:cut])
            if head in fi.bindings or (cut == 1 and head in fi.top):
                t, via = self.resolve_name(fi, head)
                for attr in parts[cut:]:
                    if isinstance(t, Module):
                        t, via = self.lookup(t.path, attr)
                    elif isinstance(t, SymRef) and self._sym(t).kind == "class":
                        m = self.method_of(t, attr)
                        t = m[0] if m else None
                    else:
                        return (t, via) if t == "external" else (None, "name_not_in_module")
                return t, via or "module_attr"
        return None, ""

    def _sym(self, ref: SymRef) -> Symbol:
        return self.files[ref.path].syms[ref.idx]

    def method_of(self, cls: SymRef, name: str, depth: int = 0) -> tuple[SymRef, bool] | None:
        """(method, inherited?) by walking the class and then its bases (resolved like any name in the class's file)."""
        if depth > MAX_HOPS:
            return None
        fi = self.files[cls.path]
        cname = self._sym(cls).name
        if (cname, name) in fi.methods:
            return SymRef(cls.path, fi.methods[(cname, name)]), depth > 0
        for base in self._sym(cls).bases:
            t, _ = self.resolve_name(fi, base)
            if isinstance(t, SymRef) and self._sym(t).kind == "class":
                found = self.method_of(t, name, depth + 1)
                if found:
                    return found[0], True
        return None

    @staticmethod
    def _caller(fi: FileIndex, idx: int | None) -> SymRef | None:
        return SymRef(fi.path, idx) if idx is not None else None

    def _bases_known(self, cls: SymRef) -> bool:
        fi = self.files[cls.path]
        return all(isinstance(self.resolve_name(fi, b)[0], SymRef) for b in self._sym(cls).bases)

    def _weak(self, pool: list[SymRef], exclude: str | None = None, caller: SymRef | None = None,
              from_test: bool = False) -> list[SymRef] | str:
        cands = [r for r in pool if r.path != exclude] if exclude else list(pool)
        if not from_test:            # library code never calls into test files
            cands = [r for r in cands if not self.files[r.path].is_test]
        if caller is not None:   # the caller itself and its own overload stubs (@overload / TS overload signatures)
            me = self._sym(caller)
            cands = [r for r in cands if not (r.path == caller.path and self._sym(r).name == me.name
                                              and self._sym(r).parent == me.parent)]
        if not cands:
            return []
        return cands if len(cands) <= MAX_WEAK else "ambiguous"

    def _type_of(self, fi: FileIndex, q: str, line: int, caller: int | None, cls: int | None) -> str | None:
        """Type hint for receiver `q` visible at `line`: same function (or module level), or for self.x / this.x
        anywhere in the enclosing class. The latest hint before the call wins."""
        best = None
        for vt in fi.var_types:
            if vt.name != q:
                continue
            if q.split(".", 1)[0] in SELF:
                if cls is None:
                    continue
                c = fi.syms[cls]
                if not (c.start_line <= vt.line <= c.end_line):
                    continue
            else:
                if caller is not None:
                    s = fi.syms[caller]
                    if not (s.start_line <= vt.line <= s.end_line) or vt.line > line:
                        continue
                elif fi.innermost(vt.line, ("function", "method")) is not None or vt.line > line:
                    continue
            if best is None or vt.line >= best.line:
                best = vt
        return best.type_name if best else None

    # -- one call --
    def resolve_call(self, fi: FileIndex, c: CallSite) -> tuple[list[tuple[SymRef, str, str]], str]:
        """([(callee, confidence, via)], outcome) where outcome is "ok", "external" or an unresolved reason."""
        if c.kind == "dynamic" or not c.callee:
            return [], "dynamic"
        caller = fi.innermost(c.line, ("function", "method"))
        cls = fi.innermost(c.line, ("class",))
        q = c.qualifier

        if q is None:
            # nested function of the caller, then file-level definitions
            if caller is not None:
                cname = fi.syms[caller].name
                for i, s in enumerate(fi.syms):
                    if s.name == c.callee and s.parent == cname and s.kind == "function" \
                            and fi.syms[caller].start_line <= s.start_line <= fi.syms[caller].end_line:
                        return [(SymRef(fi.path, i), "exact", "same_file")], "ok"
            if c.callee in fi.top:
                return [(SymRef(fi.path, fi.top[c.callee]), "exact", "same_file")], "ok"
            if c.callee in fi.bindings:
                t, via = self.resolve_binding(fi, c.callee)
                if isinstance(t, Module):            # const express = require('./express'); express()
                    t, _ = self.lookup(t.path, "default")
                    via = "import"
                if isinstance(t, SymRef):
                    return [(t, "exact", via)], "ok"
                if t == "external":
                    return [], "external"
                return [], via if via in ("import_unresolved", "name_not_in_module") else "name_not_in_module"
            for r in fi.wildcards:
                t, _ = self._through(r, c.callee, frozenset(), "wildcard")
                if isinstance(t, SymRef):
                    return [(t, "probable", "wildcard")], "ok"
            if (fi.is_py and c.callee in PY_BUILTINS) or (not fi.is_py and c.callee in JS_GLOBALS):
                return [], "external"
            if caller is not None and c.callee in [p.lstrip("*") for p in fi.syms[caller].params]:
                return [], "external"                  # calling a parameter (a callback): its value is unknown
            # A bare name defined in another module cannot be called without importing it, except between classic
            # JS scripts (shared global scope). Anything else is a local variable, a global injected at runtime, or a
            # missing import: say so instead of guessing.
            if fi.is_script:
                pool = [r for r in self.top_by_name.get(c.callee, []) if self.files[r.path].is_script]
                weak = self._weak(pool, exclude=fi.path, from_test=fi.is_test)
                if weak == "ambiguous":
                    return [], "ambiguous"
                if weak:
                    return [(r, "weak", "script_global") for r in weak], "ok"
            elsewhere = [r for r in self.top_by_name.get(c.callee, []) if r.path != fi.path]
            return [], ("not_imported" if elsewhere else "external")

        if q in SELF or q == "super":
            if cls is None:
                return [], "method_not_found"
            cref = SymRef(fi.path, cls)
            if q == "super":
                for base in fi.syms[cls].bases:
                    t, _ = self.resolve_name(fi, base)
                    if isinstance(t, SymRef) and self._sym(t).kind == "class":
                        found = self.method_of(t, c.callee)
                        if found:
                            return [(found[0], "probable", "super")], "ok"
                    elif t == "external" or (fi.is_py and base in PY_BUILTINS) or (not fi.is_py and base in JS_GLOBALS):
                        return [], "external"
                return [], "base_unknown"
            found = self.method_of(cref, c.callee)
            if found:
                return [(found[0], "probable" if found[1] else "exact", "inherited" if found[1] else "self")], "ok"
            if fi.syms[cls].bases and not self._bases_known(cref):
                return [], "base_unknown"                     # probably inherited from a class outside the repo
            weak = self._weak(self.methods_by_name.get(c.callee, []), caller=self._caller(fi, caller), from_test=fi.is_test)
            if weak == "ambiguous":
                return [], "ambiguous"
            return ([(r, "weak", "name_only") for r in weak], "ok") if weak else ([], "method_not_found")

        if q != "<expr>":
            # receiver typed by a hint (x = Foo(); s: Svc; self.repo = Repo()) -> method of that class
            ty = self._type_of(fi, q, c.line, caller, cls)
            if ty:
                t, _ = self.resolve_name(fi, ty)
                if isinstance(t, SymRef) and self._sym(t).kind == "class":
                    found = self.method_of(t, c.callee)
                    if found:
                        return [(found[0], "probable", "type_hint")], "ok"
                elif t == "external":
                    return [], "external"
            # module / class / namespace named by the qualifier (mod.f(), ns.f(), Cls.create(), pkg.mod.f())
            head = q.split(".", 1)[0]
            if head in fi.bindings or head in fi.top or q in fi.bindings:
                t, via = self.resolve_name(fi, f"{q}.{c.callee}")
                if isinstance(t, SymRef):
                    s = self._sym(t)
                    owner, _ = self.resolve_name(fi, q)
                    inherited = s.kind == "method" and isinstance(owner, SymRef) and s.parent != self._sym(owner).name
                    return [(t, "probable" if inherited else "exact",
                             "inherited" if inherited else ("module_attr" if via in ("import", "module") else via))], "ok"
                if t == "external":
                    return [], "external"
                owner, why = self.resolve_name(fi, q)
                if owner == "external":
                    return [], "external"
                if isinstance(owner, (Module, SymRef)):
                    return [], "name_not_in_module"
                if why == "import_unresolved":
                    return [], "import_unresolved"

        # unknown receiver: name-only match among methods (never for names every builtin container has)
        if not fi.is_py and q is not None and q.split(".", 1)[0] in JS_GLOBAL_OBJECTS:
            return [], "external"
        if c.callee in (PY_BUILTIN_METHODS if fi.is_py else JS_BUILTIN_METHODS) or c.callee.startswith("__"):
            return [], "builtin_method_name"
        weak = self._weak(self.methods_by_name.get(c.callee, []), caller=self._caller(fi, caller), from_test=fi.is_test)
        if weak == "ambiguous":
            return [], "ambiguous"
        return ([(r, "weak", "name_only") for r in weak], "ok") if weak else ([], "external")


def build_call_graph(parsed: dict[str, ParseResult], resolutions: list[ImportResolution]) -> CallGraph:
    rv = Resolver(parsed, resolutions)
    g = CallGraph(symbols={p: r.symbols for p, r in parsed.items()})
    seen: set[tuple] = set()
    for path in sorted(parsed):
        fi = rv.files[path]
        used: set[SymRef] = set()
        for local in fi.bindings:
            t, _ = rv.resolve_binding(fi, local)
            if isinstance(t, SymRef):
                used.add(t)
        for name in fi.reexports:
            t, _ = rv.lookup(path, name)
            if isinstance(t, SymRef):
                used.add(t)
        g.uses.extend((path, r) for r in sorted(used))
        for c in parsed[path].calls:
            targets, outcome = rv.resolve_call(fi, c)
            ci = fi.innermost(c.line, ("function", "method"))
            caller = SymRef(path, ci) if ci is not None else None
            if not targets:
                if outcome == "external":
                    g.stats["external"] += 1
                else:
                    g.stats[f"unresolved:{outcome}"] += 1
                    g.unresolved.append(Unresolved(path, caller, c.callee, c.qualifier, c.line, outcome))
                continue
            for ref, conf, via in targets:
                # calling a class runs its constructor: link the constructor too (a change in __init__ hits callers)
                refs = [ref]
                s = rv._sym(ref)
                if s.kind == "class":
                    ctor = next((rv.method_of(ref, n) for n in CTOR if rv.method_of(ref, n)), None)
                    if ctor:
                        refs.append(ctor[0])
                for r in refs:
                    if caller == r:
                        continue                                   # direct recursion adds no impact information
                    key = (path, caller, r, c.line)
                    if key in seen:
                        continue
                    seen.add(key)
                    g.edges.append(CallEdge(path, caller, r, conf, c.line, "call" if c.kind == "dynamic" else c.kind, via))
                g.stats[conf] += 1
    return g
