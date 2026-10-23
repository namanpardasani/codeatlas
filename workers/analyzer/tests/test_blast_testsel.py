"""Phase 4 of Blast Radius: test discovery (pytest + JS), selection by impact, edited/new tests, full-suite fallbacks
and runner commands, end to end on small git repos."""
from pathlib import Path

from analyzer.blast.engine import analyze_commit
from analyzer.blast.snapshot import InProcessParser, build_snapshot
from analyzer.blast.source import DirSource
from analyzer.blast.testsel import discover_tests
from gitutil import DAY, T0, commit, init

P = InProcessParser()

LIB = "def parse(t):\n    return t.split(',')\n\n\ndef unrelated():\n    return 0\n"
TESTS = ("from lib import parse, unrelated\n\n\ndef test_parse():\n    assert parse('a,b') == ['a', 'b']\n\n\n"
         "def test_unrelated():\n    assert unrelated() == 0\n\n\nclass TestMore:\n    def test_again(self):\n"
         "        assert parse('x') == ['x']\n\n    def helper(self):\n        pass\n")


def repo_with(tmp_path: Path, files: dict, change: dict) -> Path:
    r = tmp_path / "r"
    init(r)
    commit(r, T0, "ann", files)
    commit(r, T0 + DAY, "bob", change)
    return r


def test_discovers_pytest_and_js_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(TESTS)
    (tmp_path / "web.test.js").write_text("describe('w', () => {\n  it('a', () => {})\n  it.todo('later')\n})\n")
    (tmp_path / "package.json").write_text('{"devDependencies": {"mocha": "1"}}')
    snap = build_snapshot(DirSource(tmp_path), parser=P)
    got = {(u.file, u.name, u.framework) for u in discover_tests(snap)}
    assert got == {("tests/test_x.py", "test_parse", "pytest"), ("tests/test_x.py", "test_unrelated", "pytest"),
                   ("tests/test_x.py", "TestMore::test_again", "pytest"), ("web.test.js", "w > a", "mocha")}


def test_selects_only_tests_that_reach_the_change(tmp_path):
    r = repo_with(tmp_path, {"lib.py": LIB, "tests/test_lib.py": TESTS},
                  {"lib.py": LIB.replace("split(',')", "split(';')")})
    sel = analyze_commit(r, "HEAD", parser=P).tests
    assert {s.unit.name for s in sel.selected} == {"test_parse", "TestMore::test_again"}
    assert sel.total == 3 and not sel.full_suite
    assert sel.command == "pytest tests/test_lib.py::test_parse tests/test_lib.py::TestMore::test_again" or \
        sel.command == "pytest tests/test_lib.py::TestMore::test_again tests/test_lib.py::test_parse"
    assert sel.summary() == "2 of 3 tests selected (67%)"


def test_edited_and_new_tests_always_run(tmp_path):
    edited = TESTS.replace("assert unrelated() == 0", "assert unrelated() == 0  # check\n    assert True") + \
        "\n\ndef test_brand_new():\n    assert True\n"
    r = repo_with(tmp_path, {"lib.py": LIB, "tests/test_lib.py": TESTS}, {"tests/test_lib.py": edited})
    sel = analyze_commit(r, "HEAD", parser=P).tests
    assert {s.unit.name for s in sel.selected} == {"test_unrelated"}
    assert [u.name for u in sel.new_tests] == ["test_brand_new"]
    assert sel.summary() == "1 of 3 tests selected (33%) + 1 new"


def test_full_suite_when_test_setup_or_build_changes(tmp_path):
    r = repo_with(tmp_path, {"lib.py": LIB, "tests/test_lib.py": TESTS, "conftest.py": "import pytest\n"},
                  {"conftest.py": "import pytest\n\n\n@pytest.fixture\ndef db():\n    return 1\n"})
    sel = analyze_commit(r, "HEAD", parser=P).tests
    assert sel.full_suite and "test setup changed" in sel.full_suite_reasons[0] and sel.command == "pytest"
    r2 = repo_with(tmp_path / "b", {"lib.py": LIB, "tests/test_lib.py": TESTS, "pyproject.toml": "[project]\n"},
                   {"pyproject.toml": "[project]\nname = 'x'\n"})
    assert analyze_commit(r2, "HEAD", parser=P).tests.full_suite


def test_full_suite_when_no_test_reaches_changed_source(tmp_path):
    r = repo_with(tmp_path, {"lib.py": LIB, "orphan.py": "def lonely():\n    return 1\n", "tests/test_lib.py": TESTS},
                  {"orphan.py": "def lonely():\n    return 2\n"})
    sel = analyze_commit(r, "HEAD", parser=P).tests
    assert sel.full_suite and "no test reaches it" in sel.full_suite_reasons[0]


def test_js_vitest_command_with_names(tmp_path):
    lib = "export function add(a, b) { return a + b }\n"
    tst = ("import { describe, it, expect } from 'vitest'\nimport { add } from './add.js'\n"
           "describe('add', () => {\n  it('sums', () => { expect(add(1, 2)).toBe(3) })\n  it('other', () => { expect(1).toBe(1) })\n})\n")
    r = repo_with(tmp_path, {"add.js": lib, "add.test.js": tst}, {"add.js": lib.replace("a + b", "b + a")})
    sel = analyze_commit(r, "HEAD", parser=P).tests
    assert [s.unit.name for s in sel.selected] == ["add > sums"]
    assert sel.framework == "vitest" and sel.command == 'npx vitest run add.test.js -t "sums"'
