"""The hotspot scoring formula.

    score = 100 * sum_f weight_f * points_f          (weights normalized to sum to 1)

Idea: a hotspot is code that is hard to understand AND keeps changing (Tornhill). So the two
dominant factors share ONE multiplicative core, and the structural/quality factors are additive:

    core = complexity_n * churn_n          (complexity_n alone when there is no usable git history)

    complexity  points = core                     "how risky is changing this?"
    churn       points = core                     (same core: it needs BOTH to be high)
    cycle       points = cycle_n                  in a circular-dependency group, bigger group = worse
    fan_in      points = fan_in_n                 blast radius: many files import it
    no_test     points = (0 if has_test else 1) * (0.3 + 0.7 * complexity_n)
                                                  missing tests matter more for complex code
    duplication points = min(dup_ratio / 0.30, 1) 30%+ duplicated lines = maximum

Normalization (every factor is mapped to 0..1 BEFORE combining, so units do not decide):

    complexity_n = 0.5 * min(max_complexity / 25, 1)  + 0.5 * percentile(total_complexity)
                   worst function (absolute: 25+ is "very complex" anywhere) blended with how much
                   branching logic the file holds compared to the rest of THIS repo
    churn_n      = 0 if churn == 0 else 0.5 * min(c / 15, 1) + 0.5 * percentile(c)
                   c = commits in the window; if NO file in the repo changed in the window, the
                   window is quiet (CI-only commits, dormant project) and c = commits_total instead
    cycle_n      = 0 if not in a cycle else 0.5 + 0.5 * min(log2(cycle_size) / 5, 1)   (2 files -> 0.6, 32+ -> 1.0)
    fan_in_n     = 0.5 * min(log1p(fan_in) / log1p(20), 1) + 0.5 * percentile(fan_in)

Why a blend of absolute cap and percentile: a pure percentile always crowns something (the "worst" file of
a spotless repo still ranks 100%), a pure cap ignores how a repo's own scale looks. The mean keeps both
checks honest. A raw 0 is always 0 (never inflated by mid-rank ties).

Files that are tests, or shorter than config.min_lines, score 0. All weights/thresholds live in
HotspotConfig so the formula can be re-tuned without code changes.
"""
import math

from .config import FACTORS, HotspotConfig
from .types import HotspotInputs, HotspotScore, RepoContext

CC_CAP = 25            # cyclomatic complexity treated as "maximal" in absolute terms
CHURN_CAP = 15         # commits per window treated as "maximal" churn
FAN_IN_CAP = 20
DUP_CAP = 0.30
NO_TEST_BASE = 0.3     # share of the no-test penalty that applies even to trivial files


def _pct(ctx: RepoContext, name: str, value: float) -> float:
    return ctx.percentile(name, value) if value > 0 else 0.0


def _blend(absolute: float, relative: float) -> float:
    return 0.5 * min(max(absolute, 0.0), 1.0) + 0.5 * min(max(relative, 0.0), 1.0)


def _churn_value(i: HotspotInputs, ctx: RepoContext) -> tuple[float, str]:
    """(commits to use, which field they come from). Quiet window -> fall back to all history."""
    if ctx.maximum("churn") > 0:
        return float(i.churn), "churn"
    return float(i.commits_total), "commits_total"


def score_file(inputs: HotspotInputs, ctx: RepoContext, config: HotspotConfig) -> HotspotScore:
    zero = dict.fromkeys(FACTORS, 0.0)
    if (inputs.is_test and config.exclude_tests) or inputs.lines < config.min_lines:
        return HotspotScore(0.0, dict(zero), dict(zero))

    w = config.normalized_weights()

    complexity_n = _blend(inputs.max_complexity / CC_CAP, _pct(ctx, "total_complexity", inputs.total_complexity))

    churn_n = 0.0
    if ctx.history_available:
        c, field = _churn_value(inputs, ctx)
        churn_n = 0.0 if c <= 0 else _blend(c / CHURN_CAP, _pct(ctx, field, c))

    core = complexity_n * churn_n if ctx.history_available else complexity_n

    cycle_n = 0.0
    if inputs.in_cycle:
        cycle_n = 0.5 + 0.5 * min(math.log2(max(inputs.cycle_size, 2)) / 5, 1.0)

    fan_in_n = _blend(math.log1p(inputs.fan_in) / math.log1p(FAN_IN_CAP), _pct(ctx, "fan_in", inputs.fan_in))
    no_test_n = 0.0 if inputs.has_test else NO_TEST_BASE + (1 - NO_TEST_BASE) * complexity_n
    dup_n = min(max(inputs.dup_ratio, 0.0) / DUP_CAP, 1.0)

    points = {
        "complexity": core,
        "churn": core if ctx.history_available else 0.0,
        "cycle": cycle_n,
        "fan_in": fan_in_n,
        "no_test": no_test_n,
        "duplication": dup_n,
    }
    contributions = {f: 100.0 * w[f] * points[f] for f in FACTORS}
    # the factor values explain() uses for severity ("how bad is THIS factor on its own?")
    normalized = {**points, "complexity": complexity_n, "churn": churn_n}
    return HotspotScore(sum(contributions.values()), contributions, normalized)
