import json
import os
from dataclasses import asdict, dataclass, field

FACTORS = ("complexity", "churn", "cycle", "fan_in", "no_test", "duplication")


@dataclass
class HotspotConfig:
    """All tunable knobs. A formula should read weights/thresholds from here, never hard-code them,
    so the scoring can be re-tuned (env HOTSPOT_CONFIG='{"weights": {...}}') without code changes.
    The defaults are a PROPOSAL, not the formula: change freely."""
    weights: dict[str, float] = field(default_factory=lambda: {
        "complexity": 0.30, "churn": 0.30, "cycle": 0.10, "fan_in": 0.10, "no_test": 0.10, "duplication": 0.10})
    min_lines: int = 10               # ignore tiny files (re-export barrels, config stubs)
    exclude_tests: bool = True        # test files are never hotspots
    severity_high: float = 0.80       # normalized factor value at or above which a reason is "high"
    severity_medium: float = 0.50
    reason_count: int = 3             # how many reasons explain() returns
    min_points: float = 1.0           # reasons contributing fewer points are not worth mentioning

    def validate(self) -> "HotspotConfig":
        unknown = set(self.weights) - set(FACTORS)
        if unknown:
            raise ValueError(f"unknown factors in weights: {sorted(unknown)}")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be >= 0")
        if sum(self.weights.values()) <= 0:
            raise ValueError("at least one weight must be positive")
        return self

    def normalized_weights(self) -> dict[str, float]:
        """Weights scaled to sum to 1 (missing factors count as 0)."""
        total = sum(self.weights.get(f, 0.0) for f in FACTORS)
        return {f: self.weights.get(f, 0.0) / total for f in FACTORS}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HotspotConfig":
        base = cls()
        merged = {**asdict(base), **{k: v for k, v in data.items() if k != "weights"}}
        merged["weights"] = {**base.weights, **data.get("weights", {})}
        return cls(**merged).validate()

    @classmethod
    def from_env(cls) -> "HotspotConfig":
        raw = os.environ.get("HOTSPOT_CONFIG")
        return cls.from_dict(json.loads(raw)) if raw else cls().validate()
