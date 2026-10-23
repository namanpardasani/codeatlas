"""Co-change rules mined from history (association rules over commits).

Each commit is a "basket" of files. For files A and B:
  support(A, B)    = number of commits that touched both
  confidence(A->B) = support(A, B) / commits(A)  = P(B changes | A changes)
Confidence is DIRECTIONAL: a tiny helper changed in every commit that touches a big module gives
confidence(helper -> module) low but confidence(module -> helper) high.

Why it matters: it catches coupling that static analysis cannot see (a handler and its config, a model and its migration,
code and the docs or tests that always move with it, calls through dynamic dispatch).

Noise control:
  - commits touching more than `max_files` files are skipped: mass renames, formatting runs and vendoring say nothing
    about which files belong together, and a single 400-file commit would create ~80,000 pairs;
  - lockfiles, generated files and vendored folders (node_modules, dist, ...) are ignored, as in the inventory;
  - a rule needs `min_support` shared commits (one shared commit is coincidence) and `min_confidence`;
  - each file keeps only its `top_k` strongest rules, so storage stays linear in the number of files.
"""
from collections import Counter
from dataclasses import dataclass, field

from ..inventory import skipped_dir, skipped_name
from .history import Commit, canonicalize


@dataclass(frozen=True)
class Rule:
    source: str
    target: str
    support: int          # commits that touched both
    confidence: float     # P(target changes | source changes)


@dataclass
class CoChangeModel:
    commits_used: int = 0
    commits_skipped_large: int = 0
    file_commits: Counter = field(default_factory=Counter)      # commits that touched each file (after filtering)
    rules: dict[str, list[Rule]] = field(default_factory=dict)  # source -> rules, strongest first

    def partners(self, path: str) -> list[Rule]:
        return self.rules.get(path, [])

    def confidence(self, source: str, target: str) -> float:
        for r in self.rules.get(source, []):
            if r.target == target:
                return r.confidence
        return 0.0


def _ignored(path: str) -> bool:
    parts = path.split("/")
    return skipped_name(parts[-1]) or skipped_dir(parts[:-1])


def build_cochange(commits: list[Commit], *, tracked: set[str] | None = None, max_files: int = 50,
                   min_support: int = 2, min_confidence: float = 0.1, top_k: int = 25,
                   exclude: set[str] | None = None) -> CoChangeModel:
    """`tracked`: only these paths count (e.g. files that exist in the snapshot); None = every path in history.
    `exclude`: commit shas to ignore (e.g. the shallow-clone boundary commit).
    Paths are first mapped to their newest names (renames followed), so a move does not erase a file's history."""
    model = CoChangeModel()
    pairs: Counter = Counter()
    for c in canonicalize(commits):
        if exclude and c.sha in exclude:
            continue
        files = sorted({f for f in c.files if (tracked is None or f in tracked) and not _ignored(f)})
        if not files:
            continue
        if len(files) > max_files:
            model.commits_skipped_large += 1
            continue
        model.commits_used += 1
        model.file_commits.update(files)
        for i, a in enumerate(files):
            for b in files[i + 1:]:
                pairs[(a, b)] += 1

    out: dict[str, list[Rule]] = {}
    for (a, b), n in pairs.items():
        if n < min_support:
            continue
        for src, dst in ((a, b), (b, a)):
            conf = n / model.file_commits[src]
            if conf >= min_confidence:
                out.setdefault(src, []).append(Rule(src, dst, n, round(conf, 4)))
    for src, rules in out.items():
        rules.sort(key=lambda r: (-r.confidence, -r.support, r.target))
        out[src] = rules[:top_k]
    model.rules = dict(sorted(out.items()))
    return model
