from pathlib import Path

from analyzer.parsing import parse_source

FIX = Path(__file__).parent / "fixtures"


def parse(name):
    return parse_source(name, (FIX / name).read_bytes())


def sym(result, name):
    return next(s for s in result.symbols if s.name == name)


def test_typescript_symbols():
    r = parse("sample.ts")
    assert r.status == "ok"
    add = sym(r, "add")
    assert (add.kind, add.params, add.is_exported, add.has_doc) == ("function", ["a", "b", "...rest"], True, True)
    assert add.start_line == 2 and add.end_line == 5
    helper = sym(r, "helper")
    assert helper.parent == "add" and not helper.is_exported

    svc = sym(r, "Service")
    assert svc.kind == "class" and svc.is_default_export and svc.is_exported
    run = sym(r, "run")
    assert (run.kind, run.parent, run.params, run.has_doc) == ("method", "Service", ["job", "retries"], True)
    assert sym(r, "stop").has_doc is False
    assert sym(r, "counter").kind == "method"  # arrow-function class field

    handler = sym(r, "handler")
    assert handler.kind == "function" and handler.params == ["req", "{ body }"] and handler.is_exported
    local = sym(r, "local")
    assert local.params == ["x"] and local.is_exported  # via `export { local as renamed }`

    assert sym(r, "Options").kind == "interface"
    assert sym(r, "Id").kind == "type"
    assert sym(r, "Color").kind == "enum"
    assert {"add", "default", "handler", "renamed", "y", "*"} <= set(r.exports)


def test_typescript_imports():
    r = parse("sample.ts")
    by = {(i.specifier, i.kind): i for i in r.imports}
    assert by[("node:path", "import")].names == ["default", "*"]
    assert by[("./lib", "import")].names == ["a", "b"]
    assert by[("../types", "import")].is_type_only is True
    assert by[("./re", "reexport")].names == ["x"]
    assert by[("./all", "reexport")].names == ["*"]
    assert ("./cjs", "require") in by
    assert ("./lazy", "dynamic") in by
    assert all(i.specifier != "n" for i in r.imports)  # non-literal import(n) skipped


def test_tsx_and_js():
    tsx = parse("sample.tsx")
    assert tsx.status == "ok"
    assert sym(tsx, "App").is_default_export and sym(tsx, "Button").kind == "function"
    js = parse("sample.js")
    assert js.status == "ok"
    assert sym(js, "A").kind == "class" and sym(js, "method").parent == "A"
    assert sym(js, "default").is_default_export
    assert [i.specifier for i in js.imports] == ["express"]


def test_malformed_typescript_returns_partial_results():
    r = parse("broken.ts")
    assert r.status == "partial" and "line" in r.error
    assert "ok" in {s.name for s in r.symbols}


def test_deterministic():
    a, b = parse("sample.ts"), parse("sample.ts")
    assert a == b
