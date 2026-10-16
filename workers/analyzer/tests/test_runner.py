from analyzer.parsing.runner import SandboxedParser


def test_normal_parse_through_sandbox():
    with SandboxedParser(timeout_s=20) as sp:
        r = sp.parse("a.ts", b"export function f(x) {}")
        assert r.status == "ok" and r.symbols[0].name == "f"


def test_timeout_kills_child_and_recovers():
    with SandboxedParser(timeout_s=1, parse_fn="analyzer.parsing._testing:selective") as sp:
        r = sp.parse("hang.ts", b"x")
        assert r.status == "failed" and "timed out" in r.error
        assert sp.parse("fine.ts", b"x").status == "ok"  # fresh child works


def test_native_crash_is_contained():
    with SandboxedParser(timeout_s=5, parse_fn="analyzer.parsing._testing:selective") as sp:
        r = sp.parse("crash.ts", b"x")
        assert r.status == "failed" and "crashed" in r.error
        assert sp.parse("fine.ts", b"x").status == "ok"


def test_oversized_and_minified_files_are_skipped():
    from analyzer.parsing import parse_source
    big = parse_source("a.ts", b"x" * (600 * 1024))
    assert big.status == "skipped"
    minified = parse_source("a.js", b"var a=1;" * 5000)  # one 40KB line
    assert minified.status == "skipped" and "minified" in minified.error


def test_unsupported_and_empty_input():
    from analyzer.parsing import parse_source
    assert parse_source("a.rs", b"fn main() {}").status == "skipped"
    r = parse_source("a.py", b"")
    assert r.status == "ok" and r.symbols == []


def test_tree_sitter_is_pinned_below_0_26():
    """tree-sitter 0.26.0 segfaults while walking real files (found on sindresorhus/p-limit's
    test.js: native crash after Node.text on a generator function). 0.25.2 is fine.
    Upgrade only after re-running a real-repo parse."""
    import importlib.metadata as md
    assert md.version("tree-sitter").startswith("0.25."), md.version("tree-sitter")
