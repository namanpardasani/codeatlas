import pytest

from analyzer.hotspots import (FACTORS, HotspotConfig, HotspotInputs, HotspotScore, RepoContext, explain,
                               map_tests, score_all)
from analyzer.hotspots.testmap import test_stem as stem_of_test

from reference_scorer import reference_score


def test_config_defaults_validate_and_weights_normalize():
    cfg = HotspotConfig().validate()
    assert sum(cfg.normalized_weights().values()) == pytest.approx(1.0)
    assert set(cfg.weights) == set(FACTORS)


def test_config_override_merges_and_rejects_bad_input():
    cfg = HotspotConfig.from_dict({"weights": {"churn": 0.6}, "min_lines": 20})
    assert cfg.weights["churn"] == 0.6 and cfg.weights["complexity"] == 0.30 and cfg.min_lines == 20
    with pytest.raises(ValueError):
        HotspotConfig.from_dict({"weights": {"vibes": 1.0}})
    with pytest.raises(ValueError):
        HotspotConfig.from_dict({"weights": {f: 0 for f in FACTORS}})
    with pytest.raises(ValueError):
        HotspotConfig.from_dict({"weights": {"churn": -1}})


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("HOTSPOT_CONFIG", '{"weights": {"cycle": 0.5}, "reason_count": 5}')
    cfg = HotspotConfig.from_env()
    assert cfg.weights["cycle"] == 0.5 and cfg.reason_count == 5


def test_percentile_is_mid_rank_so_ties_do_not_look_like_the_top():
    pop = [HotspotInputs(path=f"f{i}.ts", churn=c) for i, c in enumerate([0] * 7 + [5, 10, 40])]
    ctx = RepoContext.build(pop, True, 90)
    assert ctx.percentile("churn", 0) == pytest.approx(0.35)   # (0 below + half of 7 equal) / 10
    assert ctx.percentile("churn", 40) == pytest.approx(0.95)
    assert ctx.percentile("churn", 1000) == 1.0 and ctx.maximum("churn") == 40
    assert RepoContext().percentile("churn", 3) == 0.0         # empty context is safe


def test_context_ignores_test_files():
    pop = [HotspotInputs(path="a.ts", churn=1), HotspotInputs(path="a.test.ts", churn=99, is_test=True)]
    assert RepoContext.build(pop, True, 90).maximum("churn") == 1


@pytest.mark.parametrize("path,expected", [
    ("src/foo.test.ts", "foo"), ("src/foo.spec.tsx", "foo"), ("tests/test_foo.py", "foo"),
    ("tests/foo_test.py", "foo"), ("src/foo.ts", None), ("src/latest.py", None), ("test_.py", None),
])
def test_test_stem(path, expected):
    assert stem_of_test(path) == expected


def test_map_tests_picks_the_closest_matching_test():
    sources = ["src/a/util.ts", "src/b/util.ts", "src/c/lonely.ts", "pkg/__init__.py", "pkg/core.py", "src/ui/index.ts"]
    tests = ["src/a/util.test.ts", "src/b/__tests__/util.spec.ts", "tests/test_core.py", "src/ui/ui.test.ts"]
    m = map_tests(sources, tests)
    assert m["src/a/util.ts"] == "src/a/util.test.ts"
    assert m["src/b/util.ts"] == "src/b/__tests__/util.spec.ts"
    assert m["src/c/lonely.ts"] is None
    assert m["pkg/core.py"] == "tests/test_core.py"
    assert m["src/ui/index.ts"] == "src/ui/ui.test.ts"   # index.ts tested via the folder name


def _scored():
    pop = [HotspotInputs(path=f"f{i}.ts", lines=100, max_complexity=5 + i, total_complexity=20 + i, churn=i,
                         function_count=4, authors=2, fan_in=i) for i in range(20)]
    hot = HotspotInputs(path="hot.ts", lines=400, max_complexity=34, total_complexity=210, function_count=12,
                        max_nesting=5, churn=18, authors=4, in_cycle=True, cycle_size=11, fan_in=14,
                        has_test=False, dup_ratio=0.23)
    ctx = RepoContext.build(pop + [hot], True, 90)
    cfg = HotspotConfig()
    return hot, ctx, cfg, reference_score(hot, ctx, cfg)


def test_explain_gives_ranked_plain_language_reasons():
    hot, ctx, cfg, s = _scored()
    reasons = explain(hot, ctx, s, cfg)
    assert 1 <= len(reasons) <= cfg.reason_count
    assert [r.points for r in reasons] == sorted((r.points for r in reasons), reverse=True)
    text = " ".join(r.text for r in reasons)
    assert "34" in text or "18 commits" in text or "circular" in text
    assert all(r.severity in ("high", "medium", "low") for r in reasons)
    assert set(reasons[0].to_dict()) == {"factor", "points", "severity", "text"}


def test_explain_skips_negligible_factors_and_zero_scores():
    hot, ctx, cfg, _ = _scored()
    zero = HotspotScore(0.0, dict.fromkeys(FACTORS, 0.0), dict.fromkeys(FACTORS, 0.0))
    assert explain(hot, ctx, zero, cfg) == []


def test_each_factor_has_a_sentence():
    hot, ctx, cfg, _ = _scored()
    for f in FACTORS:
        s = HotspotScore(50.0, {**dict.fromkeys(FACTORS, 0.0), f: 50.0}, {f: 1.0})
        r = explain(hot, ctx, s, cfg)
        assert len(r) == 1 and r[0].factor == f and r[0].severity == "high" and len(r[0].text) > 10


def test_score_all_survives_the_unimplemented_stub():
    from analyzer.hotspots import score_file
    hot, ctx, cfg, _ = _scored()
    assert score_all([hot], ctx, cfg, score_file) == [(hot, None, [])]   # stub raises -> scores are None
    done = score_all([hot], ctx, cfg, reference_score)
    assert done[0][1] is not None and done[0][2]
