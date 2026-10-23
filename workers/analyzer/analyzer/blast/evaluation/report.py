"""Combine evaluation runs into the tables of docs/BLAST_RADIUS_EVAL.md (with bootstrap intervals).

v1 (the pre-registered method) was frozen before any result was seen, so its development AND test pairs are both
unseen data for it and can be pooled. v2 was tuned on the development pairs, so it is reported on test pairs only.
"""
import glob
import json
import sys
from pathlib import Path

from . import metrics as m
from .experiment import METHODS, PairResult, summarize_tests

ROOT = Path(__file__).resolve().parents[5]
RES = ROOT / "eval" / "results"


def latest(tag: str) -> list[dict]:
    # timestamp_<tag>_pairs.json, with the tag matched exactly ("all" must not match "test_all")
    files = sorted(f for f in glob.glob(str(RES / "blast_*_pairs.json"))
                   if Path(f).name.split("_", 2)[2] == f"{tag}_pairs.json")
    if not files:
        raise SystemExit(f"no run with tag {tag}")
    return json.loads(Path(files[-1]).read_text())


def table(rows: list[dict], methods: list[str], scope: str) -> dict:
    used = [r for r in rows if not r["skipped"]]
    out = {}
    per = {}
    for meth in methods:
        rr, r5, r10 = [], [], []
        for r in used:
            truth = set(r["beyond"] if scope == "beyond" else r["truth_src"])
            if not truth:
                continue
            ranked = r["rankings"].get(meth, [])
            if scope == "beyond":
                ranked = [p for p in ranked if p not in set(r["changed"])]
            rr.append(m.reciprocal_rank(ranked, truth))
            r5.append(m.recall_at_k(ranked, truth, 5))
            r10.append(m.recall_at_k(ranked, truth, 10))
        per[meth] = (rr, r10)
        out[meth] = {"n": len(rr), "mrr": m.mean(rr), "mrr_ci": m.bootstrap_ci(rr), "recall@5": m.mean(r5),
                     "recall@10": m.mean(r10), "recall@10_ci": m.bootstrap_ci(r10)}
    base = "full"
    for meth in methods:
        if meth != base and base in per:
            out[meth]["mrr_diff_vs_full_ci"] = m.paired_diff_ci(per[meth][0], per[base][0])
            out[meth]["r10_diff_vs_full_ci"] = m.paired_diff_ci(per[meth][1], per[base][1])
    return out


def main() -> None:
    dev, test, test2, val = latest("all"), latest("test_all"), latest("test2_all"), latest("validated")
    v1 = [x for x in METHODS if not x.startswith(("v2", "v3"))]
    v2 = [x for x in METHODS if not x.startswith("v3")]
    report = {
        # each method only on pairs it was never tuned on
        "v1_pooled_dev_test_test2": {s: table(dev + test + test2, v1, s) for s in ("all", "beyond")},
        "v2_pooled_test_test2": {s: table(test + test2, v2, s) for s in ("all", "beyond")},
        "v3_test2": {s: table(test2, METHODS, s) for s in ("all", "beyond")},
        "dev_only": {s: table(dev, METHODS, s) for s in ("all", "beyond")},
        "validated_subset": {s: table(val, METHODS, s) for s in ("all", "beyond")},
        # test selection was fixed before any split was evaluated: all three splits are unseen for it
        "test_selection_pooled": summarize_tests([PairResult(**r) for r in dev + test + test2]),
        "counts": {"dev": len(dev), "test": len(test), "test2": len(test2), "validated": len(val),
                   "dev_used": sum(1 for r in dev if not r["skipped"]), "test_used": sum(1 for r in test if not r["skipped"]),
                   "test2_used": sum(1 for r in test2 if not r["skipped"])},
    }
    out = RES / "blast_summary.json"
    out.write_text(json.dumps(report, indent=1))
    fmt = lambda x: "—" if x is None else f"{x:.3f}"
    ci = lambda c: "" if not c else f" [{c[0]:.2f}, {c[1]:.2f}]"
    for name in ("v1_pooled_dev_test_test2", "v2_pooled_test_test2", "v3_test2", "validated_subset"):
        for scope in ("all", "beyond"):
            t = report[name][scope]
            print(f"\n== {name} / {scope} (n={t['full']['n']})")
            for meth, row in t.items():
                print(f"  {meth:12} MRR {fmt(row['mrr'])}{ci(row['mrr_ci'])}  R@5 {fmt(row['recall@5'])}  "
                      f"R@10 {fmt(row['recall@10'])}{ci(row['recall@10_ci'])}  dMRR vs full{ci(row.get('mrr_diff_vs_full_ci'))}")
    ts = report["test_selection_pooled"]
    print(f"\n== test selection, pooled ({ts['pairs']} pairs)")
    for k, v in ts.items():
        if isinstance(v, dict):
            print(f"  {k:24} ratio mean {fmt(v['selection_ratio_mean'])} median {fmt(v['selection_ratio_median'])} "
                  f"full-suite {fmt(v['full_suite_rate'])} file-hit {fmt(v['fix_test_file_selected'])} (n={v['n_with_fix_test_file']}) "
                  f"subset file-hit {fmt(v['fix_test_file_selected_when_subset'])} (n={v['n_subset']}) "
                  f"unit recall {fmt(v['fix_test_unit_recall'])} (n={v['n_with_fix_test_units']})")
    print(f"-> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
