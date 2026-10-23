"""Phase 5 of Blast Radius: risk features, v1 score and explanations, missing co-changes, logistic v2, reviewers."""
import math
from pathlib import Path

import pytest

from analyzer.blast.engine import analyze_commit
from analyzer.blast.history import Commit
from analyzer.blast.impact import Impact, ImpactResult, Params, Step
from analyzer.blast.reviewers import suggest_reviewers
from analyzer.blast.risk import FEATURES, WEIGHTS_V1, explain, fit_logistic, label, score_v1
from analyzer.blast.snapshot import InProcessParser
from gitutil import DAY, T0, commit, init

P = InProcessParser()


def test_v1_weights_sum_to_one_and_scale_to_100():
    assert math.isclose(sum(WEIGHTS_V1.values()), 1.0)
    assert score_v1({k: 1.0 for k in FEATURES}) == pytest.approx(100.0)
    assert score_v1({k: 0.0 for k in FEATURES}) == 0.0
    assert [label(x) for x in (10, 30, 59.9, 60, 95)] == ["low", "medium", "medium", "high", "high"]


def test_explanation_lists_strongest_factors_in_plain_words():
    f = {k: 0.0 for k in FEATURES} | {"api": 1.0, "size": 0.5, "cycle": 1.0}
    raw = {"lines": 40, "api": 3, "symbols": 2, "breadth": 0, "central_file": "", "churn_file": "", "churn": 0,
           "complexity": 0, "complex_fn": "", "missing": 0, "prior": 0}
    r = explain(f, raw, WEIGHTS_V1, score_v1(f), [], "v1")
    assert abs(r.score - 100 * (0.15 + 0.075 + 0.05)) <= 0.5 + 1e-9
    assert r.top_factors == ["3 signature/API change(s) (signature, deletion or rename)", "large change (40 lines)",
                             "touches a file in an import cycle"]


def test_logistic_learns_a_separating_feature():
    X = [{k: 0.0 for k in FEATURES} | {"api": float(i % 2)} for i in range(200)]
    y = [i % 2 for i in range(200)]
    m = fit_logistic(X, y)
    assert m.prob(X[1]) > 0.8 and m.prob(X[0]) < 0.2
    w = m.contribution_weights()
    assert max(w, key=w.get) == "api" and math.isclose(sum(w.values()), 1.0)
    assert set(m.to_json()) == {"features", "weights", "bias", "mean", "std"}


def test_risk_end_to_end_with_missing_cochange(tmp_path):
    r = tmp_path / "r"
    init(r)
    lib = "def parse(t, sep=','):\n    return t.split(sep)\n"
    commit(r, T0, "ann", {"lib.py": lib, "views.py": "from lib import parse\n\ndef show(t):\n    return parse(t)\n",
                          "tests/test_lib.py": "from lib import parse\n\ndef test_p():\n    assert parse('a')\n"})
    for i in range(4):                               # lib.py and views.py always change together
        commit(r, T0 + (i + 1) * DAY, "ann", {"lib.py": lib + f"# {i}\n", "views.py": f"from lib import parse\n\n"
                                              f"def show(t):\n    return parse(t)  # {i}\n"})
    commit(r, T0 + 9 * DAY, "zed", {"lib.py": "def parse(t):\n    return t.split(';')\n"})       # signature change, alone
    rep = analyze_commit(r, "HEAD", parser=P)
    assert rep.risk.raw["api"] == 1 and rep.risk.features["api"] == pytest.approx(1 / 3)
    assert [m.file for m in rep.risk.missing_cochanges] == ["views.py"]
    assert "usually changes with lib.py" in rep.risk.missing_cochanges[0].text()
    assert rep.risk.features["inexperience"] == 1.0                     # zed never touched lib.py before
    assert [v.name for v in rep.reviewers] == ["ann"]                   # zed (the author) excluded


def _impact(files):
    res = ImpactResult([], [], [], params=Params())
    res.files = [Impact(("file", p), s, 0, [Step(("file", p), "seed", "")]) for p, s in files]
    return res


def test_reviewers_prefer_recent_and_frequent_and_skip_bots():
    now = T0 + 400 * DAY
    hist = [Commit("1", now - 10 * DAY, "a@x", ["core.py"], name="Alice"),
            Commit("2", now - 20 * DAY, "a@x", ["core.py"], name="Alice"),
            Commit("3", now - 370 * DAY, "b@x", ["core.py", "util.py"], name="Bob"),
            Commit("4", now - 5 * DAY, "bot@x", ["core.py"], name="dependabot[bot]"),
            Commit("5", now - 1 * DAY, "me@x", ["core.py"], name="Me"),
            Commit("6", now - 1 * DAY, "c@x", ["README.md"], name="Carol")]
    revs = suggest_reviewers(_impact([("core.py", 1.0), ("util.py", 0.3), ("README.md", 1.0)]), hist, now, exclude_email="me@x")
    assert [r.name for r in revs] == ["Alice", "Bob"]                  # Carol only touched docs, bot and author skipped
    assert revs[0].commits == 2 and revs[0].reason().startswith("2 recent commit(s) to core.py")
