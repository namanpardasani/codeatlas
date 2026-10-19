"""Turn a score into human reasons: "why is this file a hotspot?"."""
from .config import HotspotConfig
from .types import HotspotInputs, HotspotScore, Reason, RepoContext


def _severity(value: float, config: HotspotConfig) -> str:
    return "high" if value >= config.severity_high else "medium" if value >= config.severity_medium else "low"


def _top(pct: float) -> str:
    return f"top {max(1, round((1 - pct) * 100))}% of files"


def _describe(factor: str, i: HotspotInputs, ctx: RepoContext) -> str:
    if factor == "complexity":
        pct = ctx.percentile("max_complexity", i.max_complexity)
        return (f"complex: worst function has cyclomatic complexity {i.max_complexity} "
                f"({_top(pct)}), {i.total_complexity} in total across {i.function_count} functions, "
                f"nesting up to {i.max_nesting}")
    if factor == "churn":
        pct = ctx.percentile("churn", i.churn)
        who = f", {i.authors} authors" if i.authors > 1 else ""
        return f"changes often: {i.churn} commits in the last {ctx.window_days} days ({_top(pct)}){who}"
    if factor == "cycle":
        return f"part of a circular dependency group of {i.cycle_size} files"
    if factor == "fan_in":
        return f"widely used: imported by {i.fan_in} files, so a change can break many places"
    if factor == "no_test":
        return "no matching test file found"
    if factor == "duplication":
        return f"{round(i.dup_ratio * 100)}% of its lines are inside duplicated blocks"
    return factor


def explain(inputs: HotspotInputs, ctx: RepoContext, score: HotspotScore, config: HotspotConfig) -> list[Reason]:
    """The factors that added the most points, most important first, each with a plain sentence."""
    ranked = sorted(score.contributions.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[Reason] = []
    for factor, points in ranked:
        if points < config.min_points:
            break
        value = score.normalized.get(factor, 0.0)
        out.append(Reason(factor, points, _severity(value, config), _describe(factor, inputs, ctx)))
        if len(out) == config.reason_count:
            break
    return out


def score_all(inputs: list[HotspotInputs], ctx: RepoContext, config: HotspotConfig, scorer):
    """Score every file with `scorer`. Returns [(inputs, score|None, reasons)]; while the formula is
    still a TODO stub the scores are None (the pipeline keeps going, hotspot columns stay empty)."""
    results = []
    for i in inputs:
        try:
            s = scorer(i, ctx, config)
        except NotImplementedError:
            return [(x, None, []) for x in inputs]
        results.append((i, s, explain(i, ctx, s, config)))
    return results
