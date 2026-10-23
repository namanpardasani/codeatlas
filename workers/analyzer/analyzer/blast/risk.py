"""Change risk score (0-100), its top factors in plain words, and missing co-change warnings.

Features are computed from the BASE of the change (code and history before it), so the score can be checked on history
without leakage. v1 is a transparent weighted sum with weights chosen by hand BEFORE any evaluation (reasons below);
v2 is a logistic regression trained on older commits and tested on newer ones (evaluation/risk_eval.py). The better
one on held-out data is the default; both are explainable through the same factors.

v1 weights (sum 1.0) and why:
  size .15          bigger diffs carry more defects (the most replicated result in defect prediction)
  api .15           signature changes, deletions and renames break callers that are not in the diff
  symbols .10       many touched functions = many places a mistake can hide
  breadth .10       a wide blast radius means more code that can be affected
  centrality .10    central files (PageRank on imports) are depended on by much of the repo
  churn .10         files that change often keep changing, often because they keep breaking
  complexity .10    complex functions are hard to change correctly
  cycle .05         files in an import cycle cannot be changed or tested in isolation
  missing_cochange .05  a file that usually changes with these did not: maybe an incomplete change
  no_tests .05      no test reaches the change
  inexperience .05  the author has rarely committed to these files before
"""
import math
from bisect import bisect_left
from dataclasses import dataclass, field

from ..graph.metrics import analyze
from .callgraph import CallGraph
from .changes import ChangeSet
from .cochange import CoChangeModel
from .history import Commit
from .impact import ImpactResult
from .snapshot import Snapshot
from .testsel import TestSelection

WEIGHTS_V1 = {"size": 0.15, "api": 0.15, "symbols": 0.10, "breadth": 0.10, "centrality": 0.10, "churn": 0.10,
              "complexity": 0.10, "cycle": 0.05, "missing_cochange": 0.05, "no_tests": 0.05, "inexperience": 0.05}
FEATURES = list(WEIGHTS_V1)

PLAIN = {
    "size": "large change ({lines} lines)",
    "api": "{api} signature/API change(s) (signature, deletion or rename)",
    "symbols": "{symbols} functions/classes changed",
    "breadth": "{breadth} other files are in its blast radius",
    "centrality": "touches a central file ({central_file})",
    "churn": "touches a frequently changed file ({churn_file}, {churn} commits in recent history)",
    "complexity": "changes a complex function ({complex_fn}, complexity {complexity})",
    "cycle": "touches a file in an import cycle",
    "missing_cochange": "{missing} file(s) that usually change with these are not in the change",
    "no_tests": "no test reaches the changed code",
    "inexperience": "the author has {prior} earlier commit(s) to these files",
}


@dataclass
class MissingCoChange:
    file: str
    partner_of: str
    confidence: float
    support: int

    def text(self) -> str:
        return (f"{self.file} usually changes with {self.partner_of} ({round(self.confidence * 100)}% of its commits, "
                f"{self.support} shared) but is not in this change")


@dataclass
class RiskResult:
    score: int
    label: str                                   # low | medium | high
    factors: list[tuple[str, float, str]]        # (feature, contribution 0-100, plain words), strongest first
    features: dict[str, float] = field(default_factory=dict)       # normalised 0..1
    raw: dict = field(default_factory=dict)                        # the numbers behind the words
    missing_cochanges: list[MissingCoChange] = field(default_factory=list)
    model: str = "v1"

    @property
    def top_factors(self) -> list[str]:
        return [words for _, c, words in self.factors[:3] if c > 0]


class GraphFacts:
    """Per-base facts that do not depend on the change (PageRank percentiles, cycles): computed once per base."""

    def __init__(self, snap: Snapshot):
        an = analyze(sorted(snap.parsed), snap.import_edges)
        order = sorted(an.pagerank.values())
        n = max(1, len(order) - 1)
        self.pr_pct = {p: bisect_left(order, r) / n for p, r in an.pagerank.items()} if len(order) > 1 else {}
        self.in_cycle = set(an.cycle_of)


def _sat(x: float, k: float) -> float:
    """Saturating 0..1: x/k capped at 1."""
    return max(0.0, min(1.0, x / k)) if k else 0.0


def features_for(changes: ChangeSet, impact: ImpactResult | None, calls: CallGraph, cochange: CoChangeModel,
                 history: list[Commit], facts: GraphFacts, tests: TestSelection | None, author_email: str | None,
                 snap: Snapshot) -> tuple[dict[str, float], dict, list[MissingCoChange]]:
    src_files = [f for f in changes.files if f.category == "code" and not f.cosmetic_only]
    old_paths = [f.old_path for f in src_files if f.old_path]
    lines = sum(f.added_lines + f.deleted_lines for f in changes.files if f.category in ("code", "test"))
    syms = changes.changed_symbols
    api = sum(1 for s in syms if s.change in ("signature", "deleted", "renamed"))
    breadth = sum(1 for i in impact.files if i.distance > 0 and i.score >= 0.1) if impact else 0
    central_file = max(old_paths, key=lambda p: facts.pr_pct.get(p, 0.0), default="")
    churn_counts = cochange.file_commits
    churn_file = max(old_paths, key=lambda p: churn_counts.get(p, 0), default="")
    churn = churn_counts.get(churn_file, 0)
    churn_pct = 0.0
    if churn_counts and churn_file:
        vals = sorted(churn_counts.values())
        churn_pct = bisect_left(vals, churn) / max(1, len(vals) - 1)
    complexity, complex_fn = 0, ""
    for s in syms:
        if s.old is not None and s.old.path in snap.parsed:
            sym = snap.parsed[s.old.path].symbols[s.old.idx]
            if (sym.complexity or 0) > complexity:
                complexity, complex_fn = sym.complexity or 0, s.name
    changed_set = {f.old_path for f in changes.files if f.old_path} | {f.path for f in changes.files}
    missing: list[MissingCoChange] = []
    for p in old_paths:
        for r in cochange.partners(p):
            if r.confidence >= 0.5 and r.support >= 3 and r.target not in changed_set and r.target in snap.files \
                    and r.target.rsplit(".", 1)[-1] not in ("md", "rst", "txt"):
                missing.append(MissingCoChange(r.target, p, r.confidence, r.support))
    missing = sorted({m.file: m for m in sorted(missing, key=lambda m: m.confidence)}.values(), key=lambda m: -m.confidence)
    prior = 0
    if author_email:
        touched = set(old_paths)
        prior = sum(1 for c in history if c.email == author_email and touched & set(c.files))
    no_tests = 1.0 if (src_files and tests is not None and not tests.selected and not tests.new_tests) else 0.0
    f = {
        "size": _sat(math.log1p(lines), math.log1p(500)),
        "api": _sat(api, 3),
        "symbols": _sat(len(syms), 10),
        "breadth": _sat(breadth, 20),
        "centrality": facts.pr_pct.get(central_file, 0.0) if central_file else 0.0,
        "churn": churn_pct,
        "complexity": _sat(complexity, 20),
        "cycle": 1.0 if any(p in facts.in_cycle for p in old_paths) else 0.0,
        "missing_cochange": _sat(len(missing), 2),
        "no_tests": no_tests,
        "inexperience": (1.0 - _sat(prior, 5)) if author_email and old_paths else 0.0,
    }
    raw = {"lines": lines, "api": api, "symbols": len(syms), "breadth": breadth, "central_file": central_file,
           "churn_file": churn_file, "churn": churn, "complexity": complexity, "complex_fn": complex_fn,
           "missing": len(missing), "prior": prior}
    return f, raw, missing


def score_v1(f: dict[str, float]) -> float:
    return 100.0 * sum(WEIGHTS_V1[k] * f.get(k, 0.0) for k in FEATURES)


def label(score: float) -> str:
    return "high" if score >= 60 else "medium" if score >= 30 else "low"


def explain(f: dict[str, float], raw: dict, weights: dict[str, float], score: float, missing, model: str) -> RiskResult:
    contribs = sorted(((k, 100.0 * weights.get(k, 0.0) * f.get(k, 0.0)) for k in FEATURES), key=lambda kv: -kv[1])
    factors = [(k, round(c, 1), PLAIN[k].format(**raw)) for k, c in contribs if c > 0]
    s = int(round(max(0.0, min(100.0, score))))
    return RiskResult(s, label(s), factors, f, raw, missing, model)


def risk(changes, impact, calls, cochange, history, facts, tests, author_email, snap, model=None) -> RiskResult:
    f, raw, missing = features_for(changes, impact, calls, cochange, history, facts, tests, author_email, snap)
    if model is not None:                     # trained v2: logistic regression on the same features
        return explain(f, raw, model.contribution_weights(), model.score(f), missing, "v2")
    return explain(f, raw, WEIGHTS_V1, score_v1(f), missing, "v1")


# ---- v2: logistic regression (numpy, no extra dependency) ------------------------------------------------------------

@dataclass
class Logistic:
    weights: list[float]
    bias: float
    mean: list[float]
    std: list[float]

    def prob(self, f: dict[str, float]) -> float:
        z = self.bias + sum(w * (f.get(k, 0.0) - m) / s for w, k, m, s in zip(self.weights, FEATURES, self.mean, self.std))
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    def score(self, f: dict[str, float]) -> float:
        return 100.0 * self.prob(f)

    def contribution_weights(self) -> dict[str, float]:
        """For explanations: positive coefficients scaled to sum 1 (negative ones lower risk and are not 'factors')."""
        pos = {k: max(0.0, w / s) for k, w, s in zip(FEATURES, self.weights, self.std)}
        tot = sum(pos.values()) or 1.0
        return {k: v / tot for k, v in pos.items()}

    def to_json(self) -> dict:
        return {"features": FEATURES, "weights": self.weights, "bias": self.bias, "mean": self.mean, "std": self.std}


def fit_logistic(X: list[dict[str, float]], y: list[int], l2: float = 1.0, iters: int = 3000, lr: float = 0.1) -> Logistic:
    import numpy as np
    A = np.array([[x.get(k, 0.0) for k in FEATURES] for x in X], dtype=float)
    mean = A.mean(axis=0)
    std = A.std(axis=0)
    std[std == 0] = 1.0
    Z = (A - mean) / std
    t = np.array(y, dtype=float)
    w = np.zeros(Z.shape[1])
    b = 0.0
    n = len(t)
    for _ in range(iters):                      # plain gradient descent with L2: small data, convex, deterministic
        p = 1.0 / (1.0 + np.exp(-(Z @ w + b)))
        g = p - t
        w -= lr * (Z.T @ g / n + l2 * w / n)
        b -= lr * g.mean()
    return Logistic(w.tolist(), float(b), mean.tolist(), std.tolist())
