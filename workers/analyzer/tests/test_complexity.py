"""Hand-counted complexity cases: the expected numbers are worked out in the comments."""
import pytest

from analyzer.parsing import parse_source

JS = b"""function simple(a) { return a; }
function branchy(a, b) {
  if (a && b) {
    for (const x of a) {
      if (x) { return 1 }
    }
  } else if (b || a) {
    return 2;
  }
  return a ? 1 : 2;
}
function sw(x) { switch (x) { case 1: return 1; case 2: return 2; default: return 0; } }
function tc() { try { risky(); } catch (e) { handle(e); } }
const cb = (items) => items.map((i) => (i > 0 ? i : 0));
function outer() { function inner() { if (x) {} } return 1; }
function nc(a, b) { a ||= b; return a ?? b; }
class K { m(a) { while (a) { if (a > 1) { a--; } } } }
"""

PY = b'''def simple(a): return a
def branchy(a, b):
    if a and b:
        for x in a:
            if x:
                return 1
    elif b or a:
        return 2
    return 1 if a else 2
def tc():
    try: risky()
    except ValueError: pass
def comp(xs): return [x for x in xs if x]
class C:
    def m(self, a, b):
        def inner():
            if a: pass
        return 1
def mt(x):
    match x:
        case 1: return 1
        case 2: return 2
        case _: return 0
'''

# name -> (complexity, max_nesting)
JS_EXPECTED = {
    "simple": (1, 0),
    "branchy": (8, 3),   # 1 + if + && + for + if + else-if(if) + || + ternary ; depth: if > for > if
    "sw": (3, 1),        # 1 + case + case (default is free)
    "tc": (2, 1),        # 1 + catch ; try opens a level
    "cb": (2, 0),        # anonymous callback's ternary counts toward the enclosing function
    "outer": (1, 0),     # nested NAMED function is excluded
    "inner": (2, 1),
    "nc": (3, 0),        # 1 + ||= + ??
    "m": (3, 2),         # 1 + while + if ; depth 2
}
PY_EXPECTED = {
    "simple": (1, 0), "branchy": (8, 3), "tc": (2, 1),
    "comp": (3, 0),      # 1 + for_in_clause + if_clause
    "m": (1, 0), "inner": (2, 1),
    "mt": (3, 1),        # 1 + case + case (`case _` is the default branch)
}


@pytest.mark.parametrize("name", JS_EXPECTED)
def test_js_complexity_and_nesting(name):
    s = next(x for x in parse_source("a.js", JS).symbols if x.name == name)
    assert (s.complexity, s.max_nesting) == JS_EXPECTED[name]


@pytest.mark.parametrize("name", PY_EXPECTED)
def test_python_complexity_and_nesting(name):
    s = next(x for x in parse_source("a.py", PY).symbols if x.name == name)
    assert (s.complexity, s.max_nesting) == PY_EXPECTED[name]


def test_classes_have_no_complexity_and_params_exclude_self():
    py = {s.name: s for s in parse_source("a.py", PY).symbols}
    assert py["C"].complexity is None
    assert py["m"].param_count == 2  # self excluded
    assert {s.name: s.param_count for s in parse_source("a.js", JS).symbols}["branchy"] == 2


def test_typescript_specific_constructs():
    ts = b"export const f = async (a?: number): Promise<number> => { if (a ?? 0) { return 1 } return a! > 2 ? 1 : 0 }"
    s = parse_source("a.ts", ts).symbols[0]
    assert s.complexity == 4  # 1 + if + ?? + ternary


def test_file_line_metrics_and_docstrings():
    src = b'''"""Module docstring
spanning two lines."""
import os

# a comment
def f(x):
    """doc"""
    return x  # trailing comment: the line is code, not a comment-only line

'''
    m = parse_source("a.py", src).metrics
    assert (m.lines, m.blank_lines) == (9, 2)
    assert m.comment_lines == 4        # 2 module-docstring lines + '# a comment' + 1 docstring line
    assert m.code_lines == 3           # import, def, return (7 non-blank - 4 comment)
    assert m.comment_ratio == pytest.approx(4 / 7, abs=1e-3)


def test_js_comment_ratio():
    m = parse_source("a.js", b"// c1\n/* c2\n   c3 */\nlet a = 1; // trailing\n\n").metrics
    assert m.comment_lines == 3 and m.code_lines == 1 and m.blank_lines == 1


def test_tokens_are_normalized_so_renames_and_literals_do_not_matter():
    a = parse_source("a.js", b"function f(x) { return x + 1; }")
    b = parse_source("b.js", b"function totallyDifferent(value) {\n  return value + 99; // note\n}")
    c = parse_source("c.js", b"function f(x) { return x - 1; }")
    assert a.token_hashes == b.token_hashes       # names, literals, whitespace, comments ignored
    assert a.token_hashes != c.token_hashes       # a different operator is different code
    assert len(a.token_hashes) == len(a.token_lines)


def test_imports_are_excluded_from_tokens():
    with_imports = parse_source("a.ts", b"import a from 'a';\nimport {b} from 'b';\nexport const z = 1;")
    without = parse_source("b.ts", b"export const z = 1;")
    assert with_imports.token_hashes == without.token_hashes
