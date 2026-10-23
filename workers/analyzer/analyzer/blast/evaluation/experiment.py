"""Run Blast Radius on each bug-INDUCING commit and score its ranking against where the bug was later FIXED.

No leakage: for an inducing commit I, the snapshot, call graph and co-change model are built at I's parent with history
up to that parent only (engine.base_model). The fix F is used only as ground truth.

Ground truth per pair:
  truth_src    existing (at I's parent, or added by I) non-test source files that F modified
  beyond       truth_src minus the files I itself changed: what propagation must find on its own
  truth_tests  test files F modified or added (used by the test-selection experiment)

Methods (all rank code files; non-code files are dropped from every ranking so lists are comparable):
  changed      baseline (a): files I changed, most changed lines first
  folder       baseline (b): changed files, then other code files in the same folders by historical churn
  imports      baseline (c): propagation over imports only
  cochange     baseline (d): propagation over co-change only
  full         Blast Radius: calls + imports + co-change, max combination
  ablations    full minus calls / imports / co-change / weak calls; calls only; noisy-OR
"""
import posixpath
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ...parsing import supported
from ..engine import BaseModel, base_model
from ..impact import Params, apply_change_paths, propagate, seeds_from
from ..inputs import EMPTY_TREE, commit_change
from ..snapshot import ParseCache
from .szz import is_source
from ...hotspots.testmap import map_tests
from ..testsel import discover_tests, select_tests

VARIANTS: dict[str, Params] = {
    "imports": Params(use_calls=False, use_cochange=False),
    "cochange": Params(use_calls=False, use_imports=False),
    "full": Params(),
    "no_calls": Params(use_calls=False),
    "no_imports": Params(use_imports=False),
    "no_cochange": Params(use_cochange=False),
    "no_weak": Params(use_weak=False),
    "calls_only": Params(use_imports=False, use_cochange=False),
    "noisy_or": Params(combine="noisy_or"),
    # v2 candidates (decided on the development set; reported on held-out pairs)
    "v2_folder": Params(use_folder=True),
    "v2_churn": Params(churn_tiebreak=True),
    "v2": Params(churn_tiebreak=True),                     # frozen after the development set
    # v3 decided after the first held-out split; judged on a second, fresh held-out split
    "v3": Params(churn_tiebreak=True, tiered=True),
}
METHODS = ["changed", "folder", *VARIANTS]


@dataclass
class PairResult:
    pair_id: str
    repo: str
    truth_src: list[str]
    beyond: list[str]
    truth_tests: list[str]
    changed: list[str]
    rankings: dict[str, list[str]] = field(default_factory=dict)
    skipped: str | None = None
    ms: dict[str, int] = field(default_factory=dict)
    change_stats: dict = field(default_factory=dict)
    impact_top: list[dict] = field(default_factory=list)     # explanation of the top files (full method)
    tests: dict = field(default_factory=dict)                 # test-selection experiment (Phase 7b)


def _baseline_changed(changes) -> list[str]:
    files = [f for f in changes.files if supported(f.path) and f.status != "deleted"]
    files.sort(key=lambda f: (-(f.added_lines + f.deleted_lines), f.path))
    return [f.path for f in files]


def _baseline_folder(changed: list[str], base: BaseModel) -> list[str]:
    dirs = {posixpath.dirname(p) for p in changed}
    churn = base.cochange.file_commits
    rest = [p for p in base.snapshot.parsed if posixpath.dirname(p) in dirs and p not in changed]
    rest.sort(key=lambda p: (-churn.get(p, 0), p))
    return changed + rest


def run_pair(repo: Path, pair: dict, cache: ParseCache, *, parser=None, max_rank: int = 200) -> PairResult:
    t: dict[str, int] = {}
    t0 = time.perf_counter()
    change = commit_change(repo, pair["inducing"], parser=parser)
    t["changes"] = int((time.perf_counter() - t0) * 1000)
    res = PairResult(pair["id"], pair["repo"], [], [], [], [])
    if change.base == EMPTY_TREE:
        res.skipped = "inducing commit is a root commit"
        return res
    base = base_model(repo, change.base, parser=parser, cache=cache, timings=t)
    known = set(base.snapshot.files) | {f.path for f in change.changes.files}
    fix_files = pair["fix_files"]
    res.truth_src = sorted(p for p, s in fix_files.items() if s in ("M", "D") and is_source(p) and p in known)
    changed_paths = {f.path for f in change.changes.files} | {f.old_path for f in change.changes.files if f.old_path}
    res.beyond = sorted(set(res.truth_src) - changed_paths)
    res.truth_tests = sorted(p for p, s in fix_files.items() if s in ("M", "A") and supported(p) and not is_source(p))
    res.changed = _baseline_changed(change.changes)
    res.change_stats = change.changes.stats()
    if not res.truth_src:
        res.skipped = "fix touches no source file that existed at the inducing commit"
        return res
    res.rankings["changed"] = res.changed[:max_rank]
    res.rankings["folder"] = _baseline_folder(res.changed, base)[:max_rank]
    seeds = seeds_from(change.changes, base.calls)
    t0 = time.perf_counter()
    for name, params in VARIANTS.items():
        r = apply_change_paths(propagate(base.graph(params), seeds), change.changes)
        res.rankings[name] = [p for p in r.ranked_files() if supported(p)][:max_rank]
        if name == "full":
            res.impact_top = [{"file": f.path_str, "score": round(f.score, 4), "distance": f.distance,
                               "why": [s.reason for s in f.path]} for f in r.files if supported(f.path_str)][:15]
    t["propagation_all_variants"] = int((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    res.tests = _test_selection(repo, pair, base, change, parser)
    t["tests"] = int((time.perf_counter() - t0) * 1000)
    res.ms = t
    return res


def _test_selection(repo: Path, pair: dict, base: BaseModel, change, parser) -> dict:
    """Selection on the INDUCING commit vs the tests the FIX later edited (existing at the inducing commit's base)."""
    product = Params(tiered=True)
    r = apply_change_paths(propagate(base.graph(product), seeds_from(change.changes, base.calls)), change.changes)
    sel = select_tests(base.snapshot, base.calls, change.changes, r)
    units = discover_tests(base.snapshot)
    unit_keys = {(u.file, u.name) for u in units}
    # baseline: every test in the test files whose name matches a changed source file (test_x.py, x.test.ts)
    changed_src = [f.path for f in change.changes.files if f.category == "code"]
    mapped = {t for t in map_tests(changed_src, base.snapshot.test_files).values() if t}
    base_units = [(u.file, u.name) for u in units if u.file in mapped]
    # ground truth from the fix: edited test files that existed, and edited test units
    fix = commit_change(repo, pair["fix"], parser=parser)
    gt_files, gt_units = set(), set()
    for f in fix.changes.files:
        if f.category == "test" and f.old_path and f.old_path in base.snapshot.files:
            gt_files.add(f.old_path)
            old = fix.changes.old_parsed.get(f.old_path)
            if old is not None:
                for u in discover_tests(base.snapshot, {f.old_path: old}):
                    if (u.file, u.name) in unit_keys and any(u.start_line <= ln <= u.end_line for ln in f.lines_old):
                        gt_units.add((u.file, u.name))
    picked = [(s_.unit.file, s_.unit.name) for s_ in sel.selected]
    return {"total": sel.total, "selected": len(picked), "new": len(sel.new_tests), "full_suite": sel.full_suite,
            "reasons": sel.full_suite_reasons, "framework": sel.framework, "selected_files": sel.files,
            "selected_units": picked[:500], "baseline_files": sorted(mapped), "baseline_units": len(base_units),
            "baseline_unit_keys": base_units[:500], "gt_files": sorted(gt_files), "gt_units": sorted(gt_units)}


def summarize_tests(results: list[PairResult]) -> dict:
    """Selection ratio, full-suite rate, and whether the fix's edited tests would have been selected."""
    rows = [r.tests for r in results if not r.skipped and r.tests and r.tests.get("total")]
    out: dict = {"pairs": len(rows)}

    def method(name, pick_files, pick_units, n_selected, full):
        ratios, file_hit, unit_rec, file_hit_subset = [], [], [], []
        for t in rows:
            fs = full(t)
            ratios.append(1.0 if fs else n_selected(t) / t["total"])
            if t["gt_files"]:
                hit = fs or bool(set(pick_files(t)) & set(t["gt_files"]))
                file_hit.append(1.0 if hit else 0.0)
                if not fs:
                    file_hit_subset.append(1.0 if set(pick_files(t)) & set(t["gt_files"]) else 0.0)
            if t["gt_units"]:
                got = {tuple(x) for x in pick_units(t)}
                unit_rec.append(1.0 if fs else len(got & {tuple(x) for x in t["gt_units"]}) / len(t["gt_units"]))
        mean = lambda xs: sum(xs) / len(xs) if xs else None
        srt = sorted(ratios)
        return {"selection_ratio_mean": mean(ratios), "selection_ratio_median": srt[len(srt) // 2] if srt else None,
                "full_suite_rate": mean([1.0 if full(t) else 0.0 for t in rows]),
                "fix_test_file_selected": mean(file_hit), "n_with_fix_test_file": len(file_hit),
                "fix_test_file_selected_when_subset": mean(file_hit_subset), "n_subset": len(file_hit_subset),
                "fix_test_unit_recall": mean(unit_rec), "n_with_fix_test_units": len(unit_rec)}

    out["blast_radius"] = method("blast", lambda t: t["selected_files"], lambda t: t["selected_units"],
                                 lambda t: t["selected"], lambda t: t["full_suite"])
    out["name_mapping_baseline"] = method("names", lambda t: t["baseline_files"], lambda t: t["baseline_unit_keys"],
                                          lambda t: t["baseline_units"], lambda t: False)
    out["blast_without_fallback"] = method("nofb", lambda t: t["selected_files"], lambda t: t["selected_units"],
                                           lambda t: t["selected"], lambda t: False)
    return out


def summarize(results: list[PairResult], metrics_mod, ks=(1, 3, 5, 10)) -> dict:
    m = metrics_mod
    used = [r for r in results if not r.skipped]
    out: dict = {"pairs_total": len(results), "pairs_used": len(used),
                 "skipped": dict(Counter(r.skipped for r in results if r.skipped)),
                 "pairs_with_beyond": sum(1 for r in used if r.beyond), "methods": {}}
    for method in METHODS:
        row: dict = {}
        for scope, truth_of, drop_changed in (("all", lambda r: set(r.truth_src), False),
                                              ("beyond", lambda r: set(r.beyond), True)):
            rr, rec, hit = [], {k: [] for k in ks}, {k: [] for k in ks}
            for r in used:
                truth = truth_of(r)
                if not truth:
                    continue
                ranked = r.rankings.get(method, [])
                if drop_changed:
                    ch = set(r.changed)
                    ranked = [p for p in ranked if p not in ch]
                rr.append(m.reciprocal_rank(ranked, truth))
                for k in ks:
                    rec[k].append(m.recall_at_k(ranked, truth, k))
                    hit[k].append(m.hit_at_k(ranked, truth, k))
            row[scope] = {"n": len(rr), "mrr": m.mean(rr), "mrr_ci": m.bootstrap_ci(rr),
                          **{f"recall@{k}": m.mean(rec[k]) for k in ks}, **{f"hit@{k}": m.mean(hit[k]) for k in ks},
                          "recall@10_ci": m.bootstrap_ci(rec[10]), "_rr": rr, "_r10": rec[10]}
        out["methods"][method] = row
    # paired differences: full vs each baseline (positive = full is better)
    full = out["methods"]["full"]
    out["paired_vs_full"] = {}
    for method in METHODS:
        if method == "full":
            continue
        other = out["methods"][method]
        out["paired_vs_full"][method] = {
            scope: {"mrr_diff_ci": m.paired_diff_ci(full[scope]["_rr"], other[scope]["_rr"]),
                    "recall@10_diff_ci": m.paired_diff_ci(full[scope]["_r10"], other[scope]["_r10"])}
            for scope in ("all", "beyond")}
    for row in out["methods"].values():
        for scope in row.values():
            scope.pop("_rr", None)
            scope.pop("_r10", None)
    return out
