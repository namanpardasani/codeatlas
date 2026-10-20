"""Metric computations. Pure functions: no database, no models, so they are cheap to test exhaustively.

Vocabulary used throughout:
  target   one thing a correct answer needs (a ground-truth file, or a ground-truth symbol when symbols are given)
  covered  for a ranked hit: the set of target indexes that hit satisfies (empty = irrelevant hit)
"""
from collections.abc import Iterable, Sequence
from math import sqrt

Covered = Sequence[frozenset[int]]


def hit_at_k(covered: Covered, k: int) -> bool:
    """Did ANY relevant result appear in the top k? (what many papers call 'recall@k' for single-answer questions)"""
    return any(c for c in covered[:k])


def recall_at_k(covered: Covered, n_targets: int, k: int) -> float:
    """Fraction of the targets found in the top k. A question needing 2 files with 1 found scores 0.5."""
    if n_targets <= 0:
        raise ValueError("a question needs at least one target")
    found: set[int] = set()
    for c in covered[:k]:
        found |= c
    return len(found) / n_targets


def reciprocal_rank(covered: Covered) -> float:
    """1/rank of the first relevant result (0 when none): rewards putting the answer FIRST."""
    for i, c in enumerate(covered, 1):
        if c:
            return 1.0 / i
    return 0.0


def first_hit_rank(covered: Covered) -> int | None:
    for i, c in enumerate(covered, 1):
        if c:
            return i
    return None


def mean(xs: Iterable[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def retrieval_summary(per_question: list[tuple[Covered, int]], ks: Sequence[int] = (1, 3, 5, 10)) -> dict:
    """per_question: [(covered per rank, n_targets)] -> {recall@k, hit@k, mrr, n}."""
    out: dict = {"n": len(per_question)}
    for k in ks:
        out[f"recall@{k}"] = mean(recall_at_k(c, n, k) for c, n in per_question)
        out[f"hit@{k}"] = mean(1.0 if hit_at_k(c, k) else 0.0 for c, _ in per_question)
    out["mrr"] = mean(reciprocal_rank(c) for c, _ in per_question)
    return out


def bootstrap_ci(values: Sequence[float], *, iters: int = 2000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float]:
    """Percentile bootstrap confidence interval of the mean. With ~50 questions the interval is wide: report it."""
    import random
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(iters))
    return (means[int(iters * alpha / 2)], means[min(iters - 1, int(iters * (1 - alpha / 2)))])


# ---- answers ----------------------------------------------------------------------------------------------
def citation_correctness(cited_paths: Sequence[str], truth_files: Sequence[str]) -> dict:
    """Do the citations point at the right files? precision = cited files that are ground truth / cited files;
    recall = ground-truth files that were cited / ground-truth files. Inferred (system-added) citations should be
    excluded by the caller: only citations the MODEL wrote say anything about the model."""
    cited, truth = set(cited_paths), set(truth_files)
    tp = len(cited & truth)
    return {"precision": tp / len(cited) if cited else None, "recall": tp / len(truth) if truth else None,
            "n_cited": len(cited)}


def refusal_stats(rows: Sequence[tuple[bool, bool]]) -> dict:
    """rows: (answerable, refused). For unanswerable questions refusing is right; for answerable ones it is a miss."""
    un = [r for a, r in rows if not a]
    an = [r for a, r in rows if a]
    return {
        "correct_refusal_rate": (sum(un) / len(un)) if un else None,   # unanswerable questions refused
        "false_refusal_rate": (sum(an) / len(an)) if an else None,     # answerable questions refused
        "n_unanswerable": len(un), "n_answerable": len(an),
    }


def rate(flags: Sequence[bool]) -> float | None:
    return sum(1 for f in flags if f) / len(flags) if flags else None


# ---- graph ------------------------------------------------------------------------------------------------
def edge_prf(predicted: Iterable[tuple[str, str]], truth: Iterable[tuple[str, str]]) -> dict:
    """Precision/recall/F1 of directed edges, plus the exact false positives and false negatives (the useful part)."""
    p, t = set(predicted), set(truth)
    tp = p & t
    prec = len(tp) / len(p) if p else (1.0 if not t else 0.0)
    rec = len(tp) / len(t) if t else (1.0 if not p else 0.0)
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": prec, "recall": rec, "f1": f1, "tp": len(tp), "predicted": len(p), "truth": len(t),
            "false_positives": sorted(p - t), "false_negatives": sorted(t - p)}


# ---- judge vs human ---------------------------------------------------------------------------------------
def agreement(a: Sequence[int], b: Sequence[int]) -> dict:
    """Judge-vs-human agreement on the same items: exact agreement, within-one agreement and Cohen's kappa
    (agreement beyond what chance would give; 0 = chance, 1 = perfect). Kappa is None when it is undefined."""
    if len(a) != len(b):
        raise ValueError("rating lists must be the same length")
    n = len(a)
    if n == 0:
        return {"n": 0, "exact": None, "within_one": None, "kappa": None}
    exact = sum(x == y for x, y in zip(a, b)) / n
    within = sum(abs(x - y) <= 1 for x, y in zip(a, b)) / n
    cats = sorted(set(a) | set(b))
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    kappa = None if pe >= 1.0 else (exact - pe) / (1 - pe)
    return {"n": n, "exact": exact, "within_one": within, "kappa": kappa}


def pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    da, db_ = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if da == 0 or db_ == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / sqrt(da * db_)
