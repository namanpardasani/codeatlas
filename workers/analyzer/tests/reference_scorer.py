"""A throwaway scorer that satisfies the hotspot contract. NEVER used by the pipeline.
It exists only to prove the contract tests are satisfiable and to catch bad scorers."""
from analyzer.hotspots import FACTORS, HotspotInputs, HotspotScore, RepoContext
from analyzer.hotspots.config import HotspotConfig


def reference_score(i: HotspotInputs, ctx: RepoContext, cfg: HotspotConfig) -> HotspotScore:
    zero = dict.fromkeys(FACTORS, 0.0)
    if (i.is_test and cfg.exclude_tests) or i.lines < cfg.min_lines:
        return HotspotScore(0.0, zero, dict(zero))
    w = cfg.normalized_weights()
    comp = min(i.max_complexity / 30, 1.0)
    churn = min(i.churn / 20, 1.0) if ctx.history_available else 0.0
    product = comp * churn if ctx.history_available else comp  # complex AND changing
    norm = {"complexity": product, "churn": product if ctx.history_available else 0.0,
            "cycle": 1.0 if i.in_cycle else 0.0, "fan_in": min(i.fan_in / 20, 1.0),
            "no_test": 0.0 if i.has_test else 1.0, "duplication": min(i.dup_ratio, 1.0)}
    contrib = {f: 100 * w[f] * norm[f] for f in FACTORS}
    return HotspotScore(sum(contrib.values()), contrib, norm)


def ignores_churn(i, ctx, cfg):
    """Deliberately wrong (breaks 'complex AND frequently changed'): must FAIL the contract."""
    return reference_score(i, type(ctx)(**{**ctx.__dict__, "history_available": False}), cfg)
