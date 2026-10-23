"""CLI for the Blast Radius evaluation. Paths are relative to the repository root (two levels above workers/analyzer)."""
import argparse
import json
import random
import sys
import time
from dataclasses import asdict
from pathlib import Path

from . import metrics
from .experiment import run_pair, summarize, summarize_tests
from .szz import mine
from ..snapshot import InProcessParser, ParseCache

ROOT = Path(__file__).resolve().parents[5]
EVAL = ROOT / "eval" / "blast"
RESULTS = ROOT / "eval" / "results"


def load_repos() -> list[dict]:
    return json.loads((EVAL / "repos.json").read_text())["repos"]


def cmd_mine(args) -> None:
    all_pairs, stats = [], {}
    skip = set()
    if args.split in ("test", "test2"):      # held-out: never a fix from an earlier split
        for name in ("pairs.json", "pairs_test.json")[: 1 if args.split == "test" else 2]:
            skip |= {p["fix"] for p in json.loads((EVAL / "dataset" / name).read_text())["pairs"]}
    for r in load_repos():
        if args.repo and r["dir"] != args.repo:
            continue
        pairs, st = mine(EVAL / ".repos" / r["dir"], r["name"], r["head"], args.limit,
                         semantic_filter=not args.raw, parser=InProcessParser(), skip_fixes=skip)
        all_pairs += [p.to_json() for p in pairs]
        stats[r["name"]] = dict(st)
    out = EVAL / "dataset" / ("pairs_raw.json" if args.raw else {"test": "pairs_test.json", "test2": "pairs_test2.json"}.get(args.split, "pairs.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "limit_per_repo": args.limit, "stats": stats,
                               "filters": "raw SZZ" if args.raw else "SZZ + functional-change filter",
                               "pairs": all_pairs}, indent=1))
    print(f"{len(all_pairs)} pairs -> {out}")


def cmd_sample(args) -> None:
    data = json.loads((EVAL / "dataset" / "pairs.json").read_text())
    rng = random.Random(args.seed)
    picked = rng.sample(data["pairs"], min(args.n, len(data["pairs"])))
    out = EVAL / "validation.json"
    existing = json.loads(out.read_text()) if out.exists() else {"reviews": []}
    done = {x["id"] for x in existing["reviews"]}
    for p in picked:
        if p["id"] not in done:
            existing["reviews"].append({"id": p["id"], "repo": p["repo"], "fix": p["fix"], "inducing": p["inducing"],
                                        "fix_subject": p["fix_subject"], "inducing_subject": p["inducing_subject"],
                                        "verdict": None, "reason": ""})
    existing["seed"] = args.seed
    out.write_text(json.dumps(existing, indent=1))
    print(f"{len(existing['reviews'])} pairs in {out}")


def cmd_run(args) -> None:
    data = json.loads((EVAL / "dataset" / {"test": "pairs_test.json", "test2": "pairs_test2.json"}.get(args.split, "pairs.json")).read_text())
    pairs = data["pairs"]
    if args.only_valid or args.validated:
        val = json.loads((EVAL / "validation.json").read_text())
        bad = {x["id"] for x in val["reviews"] if x["verdict"] == "incorrect"}
        good = {x["id"] for x in val["reviews"] if x["verdict"] == "correct"}
        pairs = [p for p in pairs if (p["id"] in good if args.validated else p["id"] not in bad)]
    repos = {r["name"]: r for r in load_repos()}
    caches: dict[str, ParseCache] = {}
    parser = InProcessParser()            # trusted, pinned open-source repos (offline evaluation only)
    results = []
    t0 = time.time()
    for i, p in enumerate(pairs, 1):
        repo = EVAL / ".repos" / repos[p["repo"]]["dir"]
        cache = caches.setdefault(p["repo"], ParseCache())
        try:
            res = run_pair(repo, p, cache, parser=parser)
        except Exception as e:  # noqa: BLE001  one broken pair must not stop the run; it is reported
            from .experiment import PairResult
            res = PairResult(p["id"], p["repo"], [], [], [], [], skipped=f"error: {type(e).__name__}: {str(e)[:120]}")
        results.append(res)
        if i % 10 == 0:
            print(f"  {i}/{len(pairs)} pairs, {time.time() - t0:.0f}s", flush=True)
    summary = summarize(results, metrics)
    summary["test_selection"] = summarize_tests(results)
    summary["by_repo"] = {name: summarize([r for r in results if r.repo == name], metrics)["methods"]["full"]
                          for name in repos}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    meta = {"run": stamp, "split": args.split, "dataset_generated": data["generated"], "only_valid": args.only_valid,
            "subset": "validated-correct pairs only" if args.validated else
                      ("all pairs minus those reviewed as incorrect" if args.only_valid else "all pairs"),
            "params": "defaults fixed before the first evaluation run (decay 0.6, depth 4, max)"}
    tag = ({"test": "test_", "test2": "test2_"}.get(args.split, "")) + ("validated" if args.validated else ("valid" if args.only_valid else "all"))
    stamp = f"{stamp}_{tag}"
    (RESULTS / f"blast_{stamp}.json").write_text(json.dumps({**meta, **summary}, indent=1, default=str))
    (RESULTS / f"blast_{stamp}_pairs.json").write_text(json.dumps([asdict(r) for r in results], indent=1, default=str))
    full, ch = summary["methods"]["full"], summary["methods"]["changed"]
    print(f"used {summary['pairs_used']}/{summary['pairs_total']} pairs; skipped {summary['skipped']}")
    for scope in ("all", "beyond"):
        print(f"[{scope}] n={full[scope]['n']}")
        for m in ("changed", "folder", "imports", "cochange", "full", "no_calls", "no_imports", "no_cochange", "no_weak",
                  "calls_only", "noisy_or", "v2_folder", "v2_churn", "v2", "v3"):
            row = summary["methods"][m][scope]
            print(f"   {m:12} MRR {row['mrr'] or 0:.3f}  R@5 {row['recall@5'] or 0:.3f}  R@10 {row['recall@10'] or 0:.3f}"
                  f"  H@10 {row['hit@10'] or 0:.3f}")
    ts = summary["test_selection"]
    for k in ("blast_radius", "blast_without_fallback", "name_mapping_baseline"):
        v = ts[k]
        print(f"   tests/{k:24} ratio mean {v['selection_ratio_mean'] or 0:.3f} median {v['selection_ratio_median'] or 0:.3f}"
              f"  full-suite {v['full_suite_rate'] or 0:.2f}  fix-test-file hit {v['fix_test_file_selected'] or 0:.3f}"
              f" (n={v['n_with_fix_test_file']})  unit recall {v['fix_test_unit_recall'] or 0:.3f} (n={v['n_with_fix_test_units']})")
    print(f"-> {RESULTS / f'blast_{stamp}.json'}")
    del ch


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m analyzer.blast.evaluation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mine")
    m.add_argument("--limit", type=int, default=45)
    m.add_argument("--repo")
    m.add_argument("--raw", action="store_true", help="plain SZZ without the functional-change filter")
    m.add_argument("--split", choices=["dev", "test", "test2"], default="dev",
                   help="test = held-out pairs: the next older fixes, excluding every development fix")
    s = sub.add_parser("sample")
    s.add_argument("--n", type=int, default=40)
    s.add_argument("--seed", type=int, default=7)
    r = sub.add_parser("run")
    r.add_argument("--only-valid", action="store_true", help="drop pairs reviewed as incorrect")
    r.add_argument("--validated", action="store_true", help="only pairs reviewed as correct")
    r.add_argument("--split", choices=["dev", "test", "test2"], default="dev")
    args = ap.parse_args(argv)
    {"mine": cmd_mine, "sample": cmd_sample, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main(sys.argv[1:])
