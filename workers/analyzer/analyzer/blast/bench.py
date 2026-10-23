"""Blast Radius benchmark: time and peak memory per change on repos of different sizes (sandboxed parser, as hosted).

    uv run python -m analyzer.blast.bench <repo dir> [n_commits]

cold = build the base model (snapshot + call graph + co-change) and analyse the change;
warm = the base model is already cached (the service keeps recent bases), only the change is analysed.
Peak RSS is this process (the sandboxed parser child is separate and bounded at 2 GB).
"""
import json
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

from .engine import base_model, commit_author
from .impact import Params, apply_change_paths, propagate, seeds_from
from .inputs import commit_change
from .reviewers import suggest_reviewers
from .risk import risk
from .snapshot import ParseCache
from .testsel import select_tests


def main() -> None:
    repo = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    shas = subprocess.run(["git", "-C", str(repo), "log", "--no-merges", "--format=%H", f"-n{n * 4}", "--", "*.py", "*.js", "*.ts"],
                          capture_output=True, text=True).stdout.split()[:n]
    cold, warm, sizes = [], [], {}
    cache = ParseCache()
    for sha in shas:
        t0 = time.perf_counter()
        change = commit_change(repo, sha)
        base = base_model(repo, change.base, cache=None)          # cold: nothing cached
        t_base = time.perf_counter()
        impact = apply_change_paths(propagate(base.graph(Params(tiered=True)), seeds_from(change.changes, base.calls)), change.changes)
        tests = select_tests(base.snapshot, base.calls, change.changes, impact)
        author, when = commit_author(repo, change.head)
        risk(change.changes, impact, base.calls, base.cochange, base.history, base.facts, tests, author, base.snapshot)
        suggest_reviewers(impact, base.history, when, exclude_email=author)
        t1 = time.perf_counter()
        # warm: same base reused, change analysed again (graph cached on the base)
        t2 = time.perf_counter()
        change2 = commit_change(repo, sha)
        impact2 = apply_change_paths(propagate(base.graph(Params(tiered=True)), seeds_from(change2.changes, base.calls)), change2.changes)
        select_tests(base.snapshot, base.calls, change2.changes, impact2)
        t3 = time.perf_counter()
        cold.append(t1 - t0)
        warm.append(t3 - t2)
        sizes = {"files": len(base.snapshot.files), "code_files": len(base.snapshot.parsed), "call_edges": len(base.calls.edges)}
        del cache
        cache = ParseCache()
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    out = {"repo": repo.name, **sizes, "commits": len(shas),
           "cold_s_median": round(statistics.median(cold), 2), "cold_s_max": round(max(cold), 2),
           "warm_s_median": round(statistics.median(warm), 3), "warm_s_max": round(max(warm), 3),
           "peak_rss_mb": round(rss_mb)}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
