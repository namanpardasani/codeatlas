"""Phase 1 of Blast Radius: call-site extraction and call resolution, scored against hand-written expected graphs.

Each fixture repo packs the tricky cases (aliases, re-exports, default exports, namespace imports, package re-exports,
submodule imports, inheritance, super, classmethod/staticmethod, type hints, nested functions, dynamic calls,
CommonJS require, JSX). Every expected edge was derived by hand from the source, including its confidence.
"""
from pathlib import Path

import pytest

from analyzer.blast.callgraph import build_call_graph
from analyzer.blast.snapshot import InProcessParser, build_snapshot
from analyzer.blast.source import DirSource

FIX = Path(__file__).parent / "fixtures" / "callgraph"

PY_EXPECTED = {
    ("pkg/util.py::helper", "pkg/util.py::slugify", "exact"),
    ("pkg/db.py::write", "pkg/db.py::connect", "exact"),
    ("pkg/models.py::Base.save", "pkg/db.py::write", "exact"),                 # from . import db; db.write()
    ("pkg/models.py::User.__init__", "pkg/util.py::slugify", "exact"),         # from .util import slugify as slug
    ("pkg/models.py::User.__init__", "pkg/models.py::Base.validate", "probable"),   # inherited
    ("pkg/models.py::User.rename", "pkg/models.py::Base.save", "probable"),
    ("pkg/models.py::User.rename", "pkg/models.py::User.display", "exact"),
    ("pkg/models.py::Admin.__init__", "pkg/models.py::User.__init__", "probable"),  # super().__init__()
    ("pkg/models.py::Admin.create", "pkg/models.py::Admin.build", "exact"),    # cls.build()
    ("pkg/models.py::Admin.build", "pkg/models.py::Admin", "exact"),           # Admin(name) -> class + constructor
    ("pkg/models.py::Admin.build", "pkg/models.py::Admin.__init__", "exact"),
    ("app.py::make", "pkg/models.py::User", "exact"),
    ("app.py::make", "pkg/models.py::User.__init__", "exact"),
    ("app.py::make", "pkg/models.py::User.rename", "probable"),                # u = User(); u.rename()
    ("app.py::make", "pkg/db.py::connect", "exact"),                           # import pkg.db; pkg.db.connect()
    ("app.py::make", "pkg/util.py::helper", "exact"),                          # from pkg import util (submodule)
    ("app.py::make", "pkg/models.py::Admin.create", "exact"),                  # Admin.create()
    ("app.py::make", "app.py::make.inner", "exact"),                           # nested function
    ("app.py::make.inner", "app.py::make", "exact"),
    ("app.py::process", "pkg/models.py::Base.save", "weak"),                   # it.save(): untyped receiver
    ("app.py::Service.__init__", "pkg/models.py::User", "exact"),
    ("app.py::Service.__init__", "pkg/models.py::User.__init__", "exact"),
    ("app.py::Service.run", "pkg/models.py::User.display", "probable"),        # self.cache = User(...)
    ("app.py::Service.run", "pkg/models.py::User.rename", "probable"),         # other: User
    ("app.py::<module>", "app.py::make", "exact"),
}
# `Account(name)` goes through the package re-export `from .models import User as Account`: same target as User(...)
# on the same line, so it shows up as the same (caller, callee) pair as the line above it; check it separately.

TS_EXPECTED = {
    ("src/lib/math.ts::double", "src/lib/math.ts::add", "exact"),
    ("src/lib/math.ts::sum", "src/lib/math.ts::add", "exact"),
    ("src/lib/store.ts::Store.put", "src/lib/store.ts::Store.log", "exact"),
    ("src/lib/store.ts::CachedStore.put", "src/lib/store.ts::Store.put", "probable"),   # super.put()
    ("src/lib/store.ts::CachedStore.put", "src/lib/store.ts::Store.get", "probable"),   # inherited this.get()
    ("src/Widget.tsx::Widget", "src/Widget.tsx::Inner", "exact"),             # <Inner />
    ("src/app.tsx::run", "src/lib/math.ts::add", "exact"),                    # plus: export { add as plus } from
    ("src/app.tsx::run", "src/lib/math.ts::double", "exact"),
    ("src/app.tsx::run", "src/lib/math.ts::sum", "exact"),                    # default import + default re-export
    ("src/app.tsx::run", "src/lib/store.ts::Store.get", "probable"),          # s: Store (via export * from)
    ("src/app.tsx::run", "src/lib/store.ts::Store.put", "weak"),              # c.put(): type unknown -> 2 candidates
    ("src/app.tsx::run", "src/lib/store.ts::CachedStore.put", "weak"),
    ("src/app.tsx::run", "src/cjs.js::helper", "exact"),                      # const { helper } = require()
    ("src/app.tsx::run", "src/Widget.tsx::Widget", "exact"),                  # <Widget /> (default import)
}


def _graph(name):
    snap = build_snapshot(DirSource(FIX / name), parser=InProcessParser())
    return build_call_graph(snap.parsed, snap.resolutions)


def _label(g, path, ref):
    return f"{path}::{g.name(ref)}" if ref is not None else f"{path}::<module>"


def _edges(g):
    return {(_label(g, e.caller_path, e.caller), f"{e.callee.path}::{g.name(e.callee)}", e.confidence) for e in g.edges}


def _score(pred, expected):
    pairs_p = {(a, b) for a, b, _ in pred}
    pairs_e = {(a, b) for a, b, _ in expected}
    tp = pairs_p & pairs_e
    return len(tp) / len(pairs_p), len(tp) / len(pairs_e), sum(1 for x in pred if x in expected) / len(expected)


@pytest.mark.parametrize("name,expected", [("py", PY_EXPECTED), ("ts", TS_EXPECTED)])
def test_call_graph_matches_hand_written_expectation(name, expected):
    g = _graph(name)
    pred = _edges(g)
    precision, recall, conf_ok = _score(pred, expected)
    missing = {(a, b, c) for a, b, c in expected if (a, b) not in {(x, y) for x, y, _ in pred}}
    extra = {(a, b, c) for a, b, c in pred if (a, b) not in {(x, y) for x, y, _ in expected}}
    wrong_conf = {x for x in pred if x not in expected and (x[0], x[1]) in {(a, b) for a, b, _ in expected}}
    assert not missing, f"missing edges: {sorted(missing)}"
    assert not extra, f"unexpected edges: {sorted(extra)}"
    assert not wrong_conf, f"wrong confidence: {sorted(wrong_conf)}"
    assert (precision, recall, conf_ok) == (1.0, 1.0, 1.0)


def test_python_unresolved_and_external_are_recorded_not_guessed():
    g = _graph("py")
    reasons = {(u.path, u.callee or "<dynamic>", u.reason) for u in g.unresolved}
    assert ("app.py", "<dynamic>", "dynamic") in reasons          # getattr(u, "display")()
    assert ("app.py", "missing", "method_not_found") in reasons   # self.missing()
    assert ("tools/run.py", "slugify", "not_imported") in reasons  # defined elsewhere but never imported: not guessed
    assert g.stats["external"] >= 4                               # json.dumps, getattr, print, len
    assert any(u.callee == "strip" and u.reason == "builtin_method_name" for u in g.unresolved)   # self.name.strip()
    assert not any(e.callee.path.endswith("json.py") for e in g.edges)


def test_package_reexport_alias_resolves_to_the_real_class():
    g = _graph("py")
    lines = {e.line for e in g.edges if e.caller_path == "app.py" and g.name(e.callee) == "User"}
    assert {9, 11} <= lines        # User(name) on line 9 and Account(name) on line 11 both reach pkg/models.py User


def test_ts_dynamic_and_externals():
    g = _graph("ts")
    assert any(u.reason == "dynamic" for u in g.unresolved)        # obj[key]()
    assert g.stats["external"] == 2                                # React.useState, setTimeout
    # untyped receivers calling Array methods: recorded, not guessed onto a repo method
    assert {(u.callee, u.reason) for u in g.unresolved if u.reason != "dynamic"} == {
        ("reduce", "builtin_method_name"), ("push", "builtin_method_name"),
        ("CachedStore", "not_imported")}                           # new CachedStore() without an import


def test_reverse_index():
    g = _graph("py")
    slug = next(e.callee for e in g.edges if g.name(e.callee) == "slugify")
    callers = {(_label(g, e.caller_path, e.caller), e.confidence) for e in g.callers_of(slug)}
    assert callers == {("pkg/util.py::helper", "exact"), ("pkg/models.py::User.__init__", "exact")}


def _parse_graph(files: dict[str, str]):
    from analyzer.parsing import parse_source
    from analyzer.resolve import resolve_imports
    from analyzer.resolve.types import ImportItem
    parsed = {p: parse_source(p, src.encode()) for p, src in files.items()}
    items = [ImportItem(p, i, im.specifier, im.kind, im.names, im.level) for p, r in parsed.items() for i, im in enumerate(r.imports)]
    return build_call_graph(parsed, resolve_imports(set(files), items, lambda _: None))


def test_weak_edges_never_point_into_tests_from_library_code():
    g = _parse_graph({
        "lib/a.py": "def run(x):\n    x.handle()\n",
        "tests/test_a.py": "class Fake:\n    def handle(self):\n        pass\n",
        "lib/b.py": "class Real:\n    def handle(self):\n        pass\n",
    })
    assert {(e.caller_path, g.name(e.callee)) for e in g.edges} == {("lib/a.py", "Real.handle")}


def test_calling_a_parameter_or_a_js_global_object_is_not_guessed():
    g = _parse_graph({
        "a.py": "def apply(hook, v):\n    return hook(v)\n",
        "b.py": "def hook(v):\n    return v\n",
        "c.js": "export function enc(s) { return Buffer.from(s) }\n",
        "d.js": "export class Box { static from(v) { return new Box() } }\n",
    })
    assert [e for e in g.edges if e.caller_path in ("a.py", "c.js")] == []    # hook(v) and Buffer.from(s): no guess


def test_classic_js_scripts_share_globals_but_modules_do_not():
    g = _parse_graph({
        "s1.js": "function util() { return 1 }\n",
        "s2.js": "function main() { return util() }\n",
        "m.js": "export function go() { return util() }\n",
    })
    assert {(e.caller_path, g.name(e.callee), e.confidence, e.via) for e in g.edges} == {("s2.js", "util", "weak", "script_global")}
    assert [(u.path, u.reason) for u in g.unresolved] == [("m.js", "not_imported")]


def test_generic_base_class_is_still_a_base():
    g = _parse_graph({"a.py": "from collections.abc import MutableMapping\nclass D(MutableMapping[str, int]):\n"
                              "    def __init__(self):\n        self.update({})\n"
                              "class Other:\n    def update(self, x):\n        pass\n"})
    assert g.edges == []                                           # inherited from an external base: not Other.update
    assert any(u.reason == "base_unknown" for u in g.unresolved) or g.stats["external"] >= 1
