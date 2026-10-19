"""The contract every hotspot scorer must satisfy (see analyzer/hotspots/scoring.py)."""
import random
from dataclasses import replace

from analyzer.hotspots import FACTORS, HotspotConfig, HotspotInputs, RepoContext


def make_population(n=60, seed=0) -> list[HotspotInputs]:
    rng = random.Random(seed)
    return [HotspotInputs(
        path=f"src/f{i}.ts", lines=rng.randrange(20, 800), code_lines=rng.randrange(10, 600),
        total_complexity=rng.randrange(1, 200), max_complexity=rng.randrange(1, 40),
        max_nesting=rng.randrange(0, 6), longest_function=rng.randrange(3, 150), function_count=rng.randrange(1, 30),
        churn=rng.choice([0, 0, 0, 1, 2, 5, 12, 30]), authors=rng.randrange(0, 8), days_since_modified=rng.randrange(0, 400),
        in_cycle=rng.random() < 0.2, cycle_size=rng.randrange(0, 12), fan_in=rng.randrange(0, 30),
        has_test=rng.random() < 0.5, dup_ratio=rng.choice([0.0, 0.0, 0.05, 0.3]),
    ) for i in range(n)]


def contexts():
    pop = make_population()
    return (RepoContext.build(pop, history_available=True, window_days=90),
            RepoContext.build(pop, history_available=False, window_days=90), pop)


def check_contract(scorer) -> None:
    ctx, ctx_nohist, pop = contexts()
    cfg = HotspotConfig()

    # 1, 2: range, sum, keys, determinism
    for i in pop:
        a, b = scorer(i, ctx, cfg), scorer(i, ctx, cfg)
        assert a == b, "not deterministic"
        assert 0 <= a.score <= 100, a.score
        assert abs(sum(a.contributions.values()) - a.score) < 1e-6, "contributions must sum to score"
        assert set(cfg.weights) <= set(a.contributions), "missing factor key"

    # 3: monotonic in each factor, all else equal
    bumps = {
        "max_complexity": lambda i: replace(i, max_complexity=i.max_complexity + 15, total_complexity=i.total_complexity + 15),
        "churn": lambda i: replace(i, churn=i.churn + 10),
        "in_cycle": lambda i: replace(i, in_cycle=True, cycle_size=max(i.cycle_size, 3)),
        "fan_in": lambda i: replace(i, fan_in=i.fan_in + 10),
        "no_test": lambda i: replace(i, has_test=False, test_file=None),
        "dup_ratio": lambda i: replace(i, dup_ratio=min(1.0, i.dup_ratio + 0.2)),
    }
    for name, bump in bumps.items():
        for i in pop:
            assert scorer(bump(i), ctx, cfg).score >= scorer(i, ctx, cfg).score - 1e-9, f"not monotonic in {name}"

    # 4: complex AND frequently changed beats complex-but-static and changed-but-trivial
    base = HotspotInputs(path="src/x.ts", lines=300, code_lines=250, fan_in=3, has_test=True)
    hot = replace(base, max_complexity=35, total_complexity=120, churn=25, authors=4)
    static = replace(hot, churn=0)
    trivial = replace(hot, max_complexity=1, total_complexity=3)
    s_hot, s_static, s_trivial = (scorer(x, ctx, cfg).score for x in (hot, static, trivial))
    assert s_hot > s_static, "complex+churny must beat complex-but-never-changed"
    assert s_hot > s_trivial, "complex+churny must beat churny-but-trivial"

    # 5: zero weight => zero contribution
    for f in FACTORS:
        c = HotspotConfig.from_dict({"weights": {f: 0.0}})
        assert scorer(hot, ctx, c).contributions[f] == 0.0, f"weight 0 for {f} must contribute 0"

    # 6: tests and tiny files
    assert scorer(replace(hot, is_test=True), ctx, cfg).score == 0
    assert scorer(replace(hot, lines=3), ctx, cfg).score == 0

    # 7: without history churn is ignored, the rest still works
    assert scorer(replace(hot, churn=0), ctx_nohist, cfg).score == scorer(hot, ctx_nohist, cfg).score
    assert scorer(replace(hot, in_cycle=True, cycle_size=5), ctx_nohist, cfg).score > scorer(hot, ctx_nohist, cfg).score
