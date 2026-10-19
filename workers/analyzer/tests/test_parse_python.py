from pathlib import Path

import pytest

from analyzer.parsing import parse_source

FIX = Path(__file__).parent / "fixtures"


def parse(name):
    return parse_source(name, (FIX / name).read_bytes())


def sym(result, name):
    return next(s for s in result.symbols if s.name == name)


def test_python_symbols():
    r = parse("sample.py")
    assert r.status == "ok"
    f = sym(r, "public_fn")
    assert (f.kind, f.params, f.has_doc, f.is_exported) == ("function", ["a", "b", "*args", "**kwargs"], True, True)
    assert sym(r, "inner").parent == "public_fn"
    assert sym(r, "_private").is_exported is False
    k = sym(r, "Klass")
    assert k.kind == "class"
    m = sym(r, "method")
    assert (m.kind, m.parent, m.params) == ("method", "Klass", ["self", "y"])
    assert sym(r, "static").kind == "method"
    assert sym(r, "handler").kind == "function" and sym(r, "handler").params == ["event"]


def test_python_exports_prefer_dunder_all():
    r = parse("sample.py")
    assert r.exports == ["Klass", "public_fn"]


def test_malformed_python_returns_partial_results():
    r = parse("broken.py")
    assert r.status == "partial"
    assert {"ok", "After"} <= {s.name for s in r.symbols}


def test_python_plain_imports():
    r = parse("sample.py")
    got = {(i.specifier, i.kind, i.level): i.names for i in r.imports}
    assert got[("os", "import", 0)] == []
    assert got[("os.path", "import", 0)] == []


def test_python_from_imports_and_relative_levels():
    r = parse("sample.py")
    got = {(i.specifier, i.kind, i.level): i.names for i in r.imports}
    assert got[("a.b", "from", 0)] == ["c", "d"]
    assert got[("", "from", 1)] == ["sibling"]
    assert got[("pkg", "from", 2)] == ["thing"]
    assert got[("m", "from", 0)] == ["*"]


def test_python_import_lines():
    r = parse("sample.py")
    assert sorted(i.line for i in r.imports) == [2, 3, 4, 5, 6, 7]
