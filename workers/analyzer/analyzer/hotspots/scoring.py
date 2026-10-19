from .config import HotspotConfig
from .types import HotspotInputs, HotspotScore, RepoContext


def score_file(inputs: HotspotInputs, ctx: RepoContext, config: HotspotConfig) -> HotspotScore:
    """TODO(user): the hotspot scoring formula. Everything around it is already built.

    CONTRACT (tests/test_hotspot_contract.py checks every line):
      1. score is in [0, 100]; contributions sum to score (within 1e-6); every factor in
         config.weights has a key in contributions (0.0 if it adds nothing).
      2. Deterministic: same inputs -> same output.
      3. Monotonic (all else equal, never LOWER): more max_complexity/total_complexity, more
         churn, being in a cycle, higher fan_in, no test file, higher dup_ratio.
      4. "Complex AND frequently changed": when ctx.history_available, a file with high churn and
         high complexity must score strictly higher than the same file with churn 0, and than the
         same churn with trivial complexity.
      5. A weight of 0 means that factor contributes exactly 0.
      6. Test files (inputs.is_test) and files shorter than config.min_lines score 0.
      7. When not ctx.history_available, churn must not be used (nothing to compare against);
         the other factors still work.

    NOTES (suggestions only, not the formula):
      * Why multiply instead of add complexity and churn? A complex file nobody touches is a
        liability but not an active risk; a churny trivial file is just busy. Risk is the product
        ("hotspot = complex AND changing"), so consider a product/geometric term for these two and
        an additive term for the rest.
      * Normalize each factor to 0..1 BEFORE combining, otherwise units (lines vs commits) decide:
          - percentile rank within the repo (ctx.percentile) is robust to outliers and needs no
            thresholds, but is always relative: the "worst" file of a clean repo still ranks 100%.
          - min(value / cap, 1) with a cap (e.g. complexity 30, churn 20/90d) is absolute but needs
            sensible caps; log(1 + x) / log(1 + max) tames heavy tails.
        A blend (max of both, or the average) is a common compromise.
      * Booleans (cycle, no_test): 1.0 / 0.0, or scale cycle by log(cycle_size) so a 40-file tangle
        outranks a 2-file loop. fan_in is a blast-radius multiplier: changing a file 30 others
        import is riskier.
      * Use config.normalized_weights() so weights always sum to 1, and put the final number on
        a 0..100 scale.
    """
    raise NotImplementedError("TODO(user): implement score_file")
