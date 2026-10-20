"""Metric definitions checked against hand-computed values (these tests ARE the metric specification)."""
import pytest

from analyzer.evalkit import metrics as m

F = frozenset
NONE = F()


def test_hit_and_recall_at_k_single_target():
    covered = [NONE, NONE, F({0}), NONE]            # the answer is at rank 3
    assert [m.hit_at_k(covered, k) for k in (1, 2, 3, 4)] == [False, False, True, True]
    assert [m.recall_at_k(covered, 1, k) for k in (1, 3)] == [0.0, 1.0]


def test_recall_at_k_counts_each_target_once_and_is_a_fraction():
    covered = [F({0}), F({0}), F({1}), NONE]        # two targets; duplicates of target 0 do not count twice
    assert m.recall_at_k(covered, 2, 1) == 0.5
    assert m.recall_at_k(covered, 2, 2) == 0.5
    assert m.recall_at_k(covered, 2, 3) == 1.0
    assert m.recall_at_k(covered, 4, 3) == 0.5      # 2 of 4 targets


def test_one_hit_may_cover_several_targets():
    assert m.recall_at_k([F({0, 1})], 2, 1) == 1.0


def test_recall_requires_targets():
    with pytest.raises(ValueError):
        m.recall_at_k([NONE], 0, 1)


def test_reciprocal_rank_and_mrr():
    assert m.reciprocal_rank([F({0})]) == 1.0
    assert m.reciprocal_rank([NONE, F({0})]) == 0.5
    assert m.reciprocal_rank([NONE, NONE, NONE, F({0})]) == 0.25
    assert m.reciprocal_rank([NONE, NONE]) == 0.0
    assert m.reciprocal_rank([]) == 0.0
    s = m.retrieval_summary([([F({0})], 1), ([NONE, F({0})], 1), ([NONE], 1)], ks=(1, 2))
    assert s["mrr"] == pytest.approx((1 + 0.5 + 0) / 3)
    assert s["recall@1"] == pytest.approx(1 / 3)
    assert s["recall@2"] == pytest.approx(2 / 3)
    assert s["n"] == 3


def test_mrr_and_recall_disagree_exactly_when_rank_matters():
    early = ([F({0})], 1)
    late = ([NONE] * 9 + [F({0})], 1)
    assert m.retrieval_summary([early], ks=(10,))["recall@10"] == m.retrieval_summary([late], ks=(10,))["recall@10"] == 1.0
    assert m.retrieval_summary([early])["mrr"] == 1.0
    assert m.retrieval_summary([late])["mrr"] == pytest.approx(0.1)


def test_first_hit_rank():
    assert m.first_hit_rank([NONE, F({1})]) == 2
    assert m.first_hit_rank([NONE]) is None


def test_bootstrap_ci_is_deterministic_and_contains_the_mean():
    xs = [1.0, 0.5, 0.0, 1.0, 0.25, 0.0, 1.0, 0.5]
    lo, hi = m.bootstrap_ci(xs)
    assert (lo, hi) == m.bootstrap_ci(xs)
    assert lo <= sum(xs) / len(xs) <= hi
    assert m.bootstrap_ci([1.0] * 10) == (1.0, 1.0)
    assert m.bootstrap_ci([]) == (0.0, 0.0)


def test_citation_correctness():
    r = m.citation_correctness(["a.py", "b.py", "a.py"], ["a.py", "c.py"])
    assert r == {"precision": 0.5, "recall": 0.5, "n_cited": 2}
    assert m.citation_correctness([], ["a.py"])["precision"] is None
    assert m.citation_correctness(["a.py"], ["a.py"])["precision"] == 1.0


def test_refusal_stats():
    r = m.refusal_stats([(True, False), (True, True), (False, True), (False, False), (False, True)])
    assert r["false_refusal_rate"] == 0.5
    assert r["correct_refusal_rate"] == pytest.approx(2 / 3)
    assert m.refusal_stats([(True, False)])["correct_refusal_rate"] is None


def test_edge_prf_values_and_diagnostics():
    pred = {("a", "b"), ("a", "c"), ("b", "c")}
    truth = {("a", "b"), ("c", "a")}
    r = m.edge_prf(pred, truth)
    assert r["precision"] == pytest.approx(1 / 3) and r["recall"] == pytest.approx(1 / 2)
    assert r["f1"] == pytest.approx(0.4)
    assert r["false_positives"] == [("a", "c"), ("b", "c")] and r["false_negatives"] == [("c", "a")]
    assert m.edge_prf(pred, pred)["f1"] == 1.0
    assert m.edge_prf(set(), set())["f1"] == 1.0
    assert m.edge_prf(set(), truth)["recall"] == 0.0 and m.edge_prf(pred, set())["precision"] == 0.0
    assert m.edge_prf({("a", "b")}, {("b", "a")})["tp"] == 0              # direction matters


def test_agreement_and_kappa():
    r = m.agreement([0, 1, 2, 2], [0, 1, 2, 1])
    assert r["exact"] == 0.75 and r["within_one"] == 1.0
    # pe = 1/4*1/4 + 1/4*2/4 + 2/4*1/4 = 0.3125 -> kappa = (0.75-0.3125)/(1-0.3125)
    assert r["kappa"] == pytest.approx(0.4375 / 0.6875)
    assert m.agreement([1, 1], [1, 1])["kappa"] is None                   # all one category: kappa undefined
    assert m.agreement([0, 2], [2, 0])["kappa"] == pytest.approx(-1.0)
    assert m.agreement([], [])["n"] == 0
    with pytest.raises(ValueError):
        m.agreement([1], [1, 2])


def test_pearson():
    assert m.pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert m.pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert m.pearson([1, 1, 1], [1, 2, 3]) is None
