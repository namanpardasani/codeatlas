"""Ranking and classification metrics for the Blast Radius evaluation. Pure functions, unit-tested.

recall@k   share of the ground-truth files that appear in the top k of the ranking (per pair, then averaged)
hit@k      1 if at least one ground-truth file is in the top k
MRR        mean over pairs of 1 / rank of the FIRST ground-truth file (0 when none is ranked)
AUC        probability that a random positive gets a higher score than a random negative (ties count half);
           0.5 = no better than chance
bootstrap  resample pairs with replacement to get a 95% interval for a mean (or a difference of means), so a small
           dataset does not pass off noise as an improvement
"""
import random
from collections.abc import Callable, Sequence


def recall_at_k(ranked: Sequence[str], truth: set[str], k: int) -> float | None:
    if not truth:
        return None
    return len(set(ranked[:k]) & truth) / len(truth)


def hit_at_k(ranked: Sequence[str], truth: set[str], k: int) -> float | None:
    if not truth:
        return None
    return 1.0 if set(ranked[:k]) & truth else 0.0


def reciprocal_rank(ranked: Sequence[str], truth: set[str]) -> float | None:
    if not truth:
        return None
    for i, item in enumerate(ranked, 1):
        if item in truth:
            return 1.0 / i
    return 0.0


def mean(xs: Sequence[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else None


def auc(pos: Sequence[float], neg: Sequence[float]) -> float | None:
    """Mann-Whitney formulation, O((n+m) log(n+m)) via ranks with average ranks for ties."""
    if not pos or not neg:
        return None
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    ranks = [0.0] * len(allv)
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        for t in range(i, j + 1):
            ranks[t] = r
        i = j + 1
    rank_sum_pos = sum(r for r, (_, label) in zip(ranks, allv) if label == 1)
    n, m = len(pos), len(neg)
    return (rank_sum_pos - n * (n + 1) / 2) / (n * m)


def precision_at_fraction(scores: Sequence[float], labels: Sequence[int], fraction: float) -> float | None:
    """Precision among the top `fraction` of items by score (e.g. top 10% riskiest commits)."""
    if not scores:
        return None
    k = max(1, round(len(scores) * fraction))
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    return sum(labels[i] for i in order) / k


def bootstrap_ci(values: Sequence[float | None], n: int = 2000, seed: int = 0, stat: Callable = None) -> tuple[float, float] | None:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    rng = random.Random(seed)
    f = stat or (lambda xs: sum(xs) / len(xs))
    samples = sorted(f([vals[rng.randrange(len(vals))] for _ in vals]) for _ in range(n))
    return samples[int(0.025 * n)], samples[int(0.975 * n) - 1]


def paired_diff_ci(a: Sequence[float | None], b: Sequence[float | None], n: int = 2000, seed: int = 0):
    """95% interval of mean(a - b) over pairs where both are defined. If it excludes 0, the difference is unlikely
    to be resampling noise."""
    diffs = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    return bootstrap_ci(diffs, n, seed)
