"""Phase 7 evaluation code: metric functions, the bug-fix filter, SZZ on a planted bug, and leakage guards."""
from pathlib import Path

import pytest

from analyzer.blast.evaluation import metrics as m
from analyzer.blast.evaluation.szz import CommitInfo, deleted_lines, functional_change, is_fix, mine
from analyzer.blast.snapshot import InProcessParser
from gitutil import DAY, T0, commit, init

P = InProcessParser()


# ---- metrics -----------------------------------------------------------------------------------------------------

def test_recall_hit_and_reciprocal_rank():
    ranked = ["a", "b", "c", "d"]
    assert m.recall_at_k(ranked, {"b", "z"}, 2) == 0.5
    assert m.hit_at_k(ranked, {"d"}, 3) == 0.0 and m.hit_at_k(ranked, {"d"}, 4) == 1.0
    assert m.reciprocal_rank(ranked, {"c", "d"}) == pytest.approx(1 / 3)
    assert m.reciprocal_rank(ranked, {"z"}) == 0.0
    assert m.recall_at_k(ranked, set(), 5) is None and m.mean([None, 1.0, 0.0]) == 0.5


def test_auc_with_ties_and_edge_cases():
    assert m.auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert m.auc([0.1], [0.9]) == 0.0
    assert m.auc([0.5, 0.5], [0.5, 0.5]) == 0.5          # ties count half
    assert m.auc([0.7, 0.4], [0.5, 0.3]) == 0.75
    assert m.auc([], [0.1]) is None


def test_precision_at_fraction_and_bootstrap():
    assert m.precision_at_fraction([0.9, 0.1, 0.8, 0.2], [1, 0, 0, 0], 0.5) == 0.5
    lo, hi = m.bootstrap_ci([1.0, 0.0] * 50, n=500, seed=1)
    assert lo < 0.5 < hi
    assert m.bootstrap_ci([1.0, 0.0] * 50, n=500, seed=1) == (lo, hi)                # deterministic for a seed
    lo, hi = m.paired_diff_ci([1.0] * 30, [0.0] * 30, n=200)
    assert lo == hi == 1.0


# ---- fix detection -----------------------------------------------------------------------------------------------

def C(subject, files, parents=("p",)):
    return CommitInfo("x" * 40, list(parents), 0, "dev", subject, files)


@pytest.mark.parametrize("subject,files,ok,why", [
    ("Fix crash on empty header", {"src/a.py": "M"}, True, "ok"),
    ("fix typo in README", {"src/a.py": "M"}, False, "excluded-message"),
    ("Fix mypy findings", {"src/a.py": "M"}, False, "non-functional-message"),
    ("Add a feature", {"src/a.py": "M"}, False, "message"),
    ("Fix flaky test", {"tests/test_a.py": "M"}, False, "excluded-message"),
    ("Fix bug", {"tests/test_a.py": "M"}, False, "no-modified-source"),
    ("Fix bug", {"src/new.py": "A"}, False, "no-modified-source"),         # pure addition: nothing to blame
    ("Fix bug", {f"src/f{i}.py": "M" for i in range(12)}, False, "too-many-files"),
])
def test_fix_filter(subject, files, ok, why):
    assert is_fix(C(subject, files)) == (ok, why)
    assert is_fix(C("Fix bug", {"src/a.py": "M"}, parents=("a", "b"))) == (False, "merge")


# ---- SZZ on a planted bug -------------------------------------------------------------------------------------------

@pytest.fixture()
def planted(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    init(r)
    commit(r, T0, "ann", {"lib/calc.py": "def total(xs):\n    s = 0\n    for x in xs:\n        s += x\n    return s\n",
                          "lib/other.py": "def other():\n    return 1\n"})
    # the bug: off-by-one introduced here
    commit(r, T0 + DAY, "bob", {"lib/calc.py": "def total(xs):\n    s = 0\n    for x in xs[1:]:\n        s += x\n    return s\n"})
    commit(r, T0 + 2 * DAY, "cy", {"lib/other.py": "def other():\n    # comment only\n    return 1\n"})
    commit(r, T0 + 3 * DAY, "dee", {"lib/calc.py": "def total(xs):\n    s = 0\n    for x in xs:\n        s += x\n    return s\n"})
    return r


def _sha(r, rev):
    import subprocess
    return subprocess.run(["git", "-C", str(r), "rev-parse", rev], capture_output=True, text=True).stdout.strip()


def test_szz_blames_the_commit_that_wrote_the_buggy_line(planted, monkeypatch):
    import analyzer.blast.evaluation.szz as szz
    monkeypatch.setattr(szz, "FIX_RE", szz.re.compile(r"c"))          # every subject in the fixture is "c": treat as fix
    monkeypatch.setattr(szz, "NOT_FIX_RE", szz.re.compile(r"$^"))
    head = _sha(planted, "HEAD")
    assert deleted_lines(planted, _sha(planted, "HEAD~1"), head, "lib/calc.py") == [3]
    pairs, stats = mine(planted, "t/r", head, 5, log=lambda *_: None, parser=P)
    by_fix = {p.fix: p for p in pairs}
    assert by_fix[head].inducing == _sha(planted, "HEAD~2")                # the off-by-one commit, not the original
    assert by_fix[head].blamed_lines == 1
    assert stats["fix:non-functional-change"] >= 1                         # the comment-only commit was filtered


def test_functional_change_filter(planted):
    assert functional_change(planted, _sha(planted, "HEAD"), P)            # real code change
    assert not functional_change(planted, _sha(planted, "HEAD~1"), P)      # comment only
