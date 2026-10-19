"""Behaviour of the real formula (beyond the generic contract)."""
from dataclasses import replace

import pytest

from analyzer.hotspots import HotspotConfig, HotspotInputs, RepoContext, explain, score_file

from hotspot_contract import check_contract, contexts

CFG = HotspotConfig()


def base(**kw):
    return HotspotInputs(path="src/x.ts", lines=300, code_lines=250, has_test=True, **kw)


def test_satisfies_the_full_contract():
    check_contract(score_file)


def test_complex_and_churny_is_the_hotspot_not_either_alone():
    ctx, _, _ = contexts()
    hot = score_file(base(max_complexity=30, total_complexity=150, churn=25, authors=4), ctx, CFG).score
    only_complex = score_file(base(max_complexity=30, total_complexity=150, churn=0), ctx, CFG).score
    only_churny = score_file(base(max_complexity=1, total_complexity=2, churn=25), ctx, CFG).score
    assert hot > 3 * max(only_complex, only_churny)
    assert only_complex < 5 and only_churny < 5   # neither alone is a hotspot


def test_structural_factors_add_points_independently():
    ctx, _, _ = contexts()
    plain = score_file(base(max_complexity=5, total_complexity=10), ctx, CFG)
    cyc = score_file(base(max_complexity=5, total_complexity=10, in_cycle=True, cycle_size=11), ctx, CFG)
    assert cyc.contributions["cycle"] > 0 and plain.contributions["cycle"] == 0
    assert cyc.score - plain.score == pytest.approx(cyc.contributions["cycle"])
    big = score_file(base(in_cycle=True, cycle_size=40), ctx, CFG).contributions["cycle"]
    small = score_file(base(in_cycle=True, cycle_size=2), ctx, CFG).contributions["cycle"]
    assert big > small


def test_missing_tests_hurt_complex_files_more():
    ctx, _, _ = contexts()
    simple = replace(base(max_complexity=2, total_complexity=4), has_test=False)
    complex_ = replace(base(max_complexity=30, total_complexity=150), has_test=False)
    assert score_file(complex_, ctx, CFG).contributions["no_test"] > score_file(simple, ctx, CFG).contributions["no_test"] > 0
    assert score_file(base(max_complexity=30), ctx, CFG).contributions["no_test"] == 0


def test_quiet_window_falls_back_to_all_history():
    # nothing changed inside the window anywhere (CI-only recent commits): use commits_total
    pop = [HotspotInputs(path=f"f{i}.ts", lines=100, max_complexity=10 + i, total_complexity=40 + i,
                         churn=0, commits_total=i) for i in range(30)]
    ctx = RepoContext.build(pop, history_available=True, window_days=90)
    busy = replace(pop[29], commits_total=28)
    dormant = replace(pop[29], commits_total=0)
    assert score_file(busy, ctx, CFG).score > score_file(dormant, ctx, CFG).score > 0 - 1e-9
    assert score_file(busy, ctx, CFG).contributions["churn"] > 0


def test_zero_churn_is_never_inflated_by_percentile_ties():
    ctx, _, _ = contexts()
    s = score_file(base(max_complexity=30, total_complexity=150, churn=0), ctx, CFG)
    assert s.normalized["churn"] == 0.0 and s.contributions["churn"] == 0.0


def test_weights_are_tunable_without_code_changes():
    ctx, _, _ = contexts()
    i = base(max_complexity=30, total_complexity=150, churn=25, in_cycle=True, cycle_size=8)
    only_cycle = HotspotConfig.from_dict({"weights": {"complexity": 0, "churn": 0, "fan_in": 0, "no_test": 0, "duplication": 0}})
    s = score_file(i, ctx, only_cycle)
    assert s.score == pytest.approx(100 * s.normalized["cycle"])  # all weight on cycle -> 100 * cycle_n


def test_explanations_name_the_dominant_factors():
    ctx, _, _ = contexts()
    i = base(max_complexity=34, total_complexity=210, churn=18, authors=4, function_count=12, max_nesting=5,
             in_cycle=True, cycle_size=11, fan_in=14, dup_ratio=0.2)
    i = replace(i, has_test=False)
    s = score_file(i, ctx, CFG)
    reasons = explain(i, ctx, s, CFG)
    assert reasons and reasons[0].severity in ("high", "medium")
    assert {r.factor for r in reasons} & {"complexity", "churn"}
    assert any("34" in r.text or "18 commits" in r.text for r in reasons)


def test_quiet_window_explanation_talks_about_history_not_zero_commits():
    pop = [HotspotInputs(path=f"f{i}.ts", lines=100, max_complexity=10 + i, total_complexity=40 + i, commits_total=i)
           for i in range(30)]
    ctx = RepoContext.build(pop, history_available=True, window_days=90)
    i = replace(pop[29], commits_total=28, authors=3)
    reasons = explain(i, ctx, score_file(i, ctx, CFG), CFG)
    churn = next(r for r in reasons if r.factor == "churn")
    assert "28 commits in the fetched history" in churn.text and "last 90 days" in churn.text
    assert "0 commits" not in churn.text
