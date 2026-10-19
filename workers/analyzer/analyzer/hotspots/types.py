from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field


@dataclass
class HotspotInputs:
    """Everything known about one source file. The scoring formula may use any of it."""
    path: str
    is_test: bool = False
    lines: int = 0
    code_lines: int = 0
    comment_ratio: float = 0.0
    # complexity (from the AST)
    total_complexity: int = 0      # sum over the file's functions
    max_complexity: int = 0        # the worst single function
    max_nesting: int = 0
    longest_function: int = 0      # lines
    function_count: int = 0
    # change history (None/0 when the clone had no usable history)
    churn: int = 0                 # commits touching the file inside the window
    commits_total: int = 0         # commits touching it in ALL fetched history (useful when the window is quiet)
    authors: int = 0
    days_since_modified: int | None = None
    # structure
    in_cycle: bool = False
    cycle_size: int = 0            # files in its circular-dependency group
    fan_in: int = 0
    fan_out: int = 0
    pagerank: float = 0.0
    # quality signals
    has_test: bool = False         # a test file with a matching name exists
    test_file: str | None = None
    dup_ratio: float = 0.0         # share of its lines inside duplicated blocks (0..1)


NUMERIC_FIELDS = ("lines", "code_lines", "comment_ratio", "total_complexity", "max_complexity", "max_nesting",
                  "longest_function", "function_count", "churn", "commits_total", "authors", "days_since_modified",
                  "fan_in", "fan_out", "pagerank", "dup_ratio")


@dataclass
class RepoContext:
    """Repo-wide distributions, so a formula can ask "is this file's churn high FOR THIS REPO?"."""
    n_files: int = 0
    history_available: bool = False   # False => churn/authors are meaningless (no usable git history)
    window_days: int = 0
    values: dict[str, list[float]] = field(default_factory=dict)  # field -> sorted values over source files

    def percentile(self, name: str, value: float) -> float:
        """Mid-rank percentile in [0, 1]: share of files below `value` plus half of those equal to it.
        Ties are common (most files have churn 0), mid-rank keeps them from all counting as "top"."""
        vs = self.values.get(name) or []
        if not vs:
            return 0.0
        return (bisect_left(vs, value) + 0.5 * (bisect_right(vs, value) - bisect_left(vs, value))) / len(vs)

    def maximum(self, name: str) -> float:
        vs = self.values.get(name) or []
        return vs[-1] if vs else 0.0

    @classmethod
    def build(cls, inputs: list[HotspotInputs], history_available: bool, window_days: int) -> "RepoContext":
        src = [i for i in inputs if not i.is_test]
        values = {f: sorted(float(getattr(i, f) or 0) for i in src) for f in NUMERIC_FIELDS}
        return cls(len(src), history_available, window_days, values)


@dataclass
class HotspotScore:
    score: float                       # 0..100
    contributions: dict[str, float]    # factor -> points it added; they sum to `score`
    normalized: dict[str, float] = field(default_factory=dict)  # factor -> 0..1 value the formula used


@dataclass
class Reason:
    factor: str
    points: float
    severity: str   # high | medium | low
    text: str

    def to_dict(self) -> dict:
        return {"factor": self.factor, "points": round(self.points, 2), "severity": self.severity, "text": self.text}
