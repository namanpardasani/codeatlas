"""Phase 5 evaluation: does the risk score rank bug-INDUCING commits above ordinary commits?

  positives  unique inducing commits of the SZZ pairs (dev + test + test2)
  negatives  random non-merge commits that touch source code in the same repos and time span, never an inducing
             commit of any pair (2 per positive per repo). Some negatives surely contain undiscovered bugs: label noise
             that makes every AUC here a lower bound on the real separability.
  split      per repo, by time: the oldest 70% of commits train v2, the newest 30% test BOTH v1 and v2 (no future data
             in training). v1 needs no training; it is evaluated on the same test rows.
  metrics    AUC, precision among the top 10% riskiest test commits; baseline: lines changed alone.
"""
import json
import random
import subprocess
import sys
import time
from pathlib import Path

from . import metrics as M
from .szz import is_source
from ..engine import analyze_commit, base_model
from ..impact import Params
from ..risk import FEATURES, fit_logistic, score_v1
from ..snapshot import InProcessParser, ParseCache

ROOT = Path(__file__).resolve().parents[5]
EVAL = ROOT / "eval" / "blast"
RES = ROOT / "eval" / "results"


def candidates(repo: Path, head: str) -> list[tuple[str, int]]:
    out = subprocess.run(["git", "-C", str(repo), "log", "--no-merges", "--name-only", "--format=\x01%H %at", head],
                         capture_output=True, text=True, errors="replace").stdout
    rows, cur, files = [], None, []
    for line in out.split("\n"):
        if line.startswith("\x01"):
            if cur and any(is_source(f) for f in files) and len(files) <= 60:
                rows.append(cur)
            sha, at = line[1:].split()
            cur, files = (sha, int(at)), []
        elif line:
            files.append(line)
    if cur and any(is_source(f) for f in files):
        rows.append(cur)
    return rows


def build_rows(limit_per_repo: int | None = None) -> list[dict]:
    repos = {r["name"]: r for r in json.loads((EVAL / "repos.json").read_text())["repos"]}
    pairs = []
    for name in ("pairs.json", "pairs_test.json", "pairs_test2.json"):
        pairs += json.loads((EVAL / "dataset" / name).read_text())["pairs"]
    rng = random.Random(42)
    parser = InProcessParser()
    rows: list[dict] = []
    for repo_name, cfg in repos.items():
        repo = EVAL / ".repos" / cfg["dir"]
        pos = sorted({(p["inducing"], p["inducing_time"]) for p in pairs if p["repo"] == repo_name}, key=lambda x: x[1])
        if limit_per_repo:
            pos = pos[-limit_per_repo:]
        if not pos:
            continue
        inducers = {p["inducing"] for p in pairs if p["repo"] == repo_name}
        lo, hi = pos[0][1], pos[-1][1]
        pool = [c for c in candidates(repo, cfg["head"]) if lo <= c[1] <= hi and c[0] not in inducers]
        neg = rng.sample(pool, min(len(pool), 2 * len(pos)))
        cache = ParseCache()
        t0 = time.time()
        for i, ((sha, at), label) in enumerate([(p, 1) for p in pos] + [(n, 0) for n in neg], 1):
            try:
                rep = analyze_commit(repo, sha, parser=parser, cache=cache, params=Params(tiered=True))
            except Exception as e:  # noqa: BLE001
                rows.append({"repo": repo_name, "sha": sha, "time": at, "label": label, "error": f"{type(e).__name__}: {e}"[:200]})
                continue
            if rep.risk is None:
                continue
            rows.append({"repo": repo_name, "sha": sha, "time": at, "label": label, "features": rep.risk.features,
                         "lines": rep.risk.raw["lines"], "v1": score_v1(rep.risk.features)})
            if i % 25 == 0:
                print(f"  {repo_name}: {i}/{len(pos) + len(neg)} ({time.time() - t0:.0f}s)", flush=True)
    return rows


def evaluate(rows: list[dict]) -> dict:
    ok = [r for r in rows if "features" in r]
    train, test = [], []
    for repo in sorted({r["repo"] for r in ok}):
        rs = sorted((r for r in ok if r["repo"] == repo), key=lambda r: r["time"])
        cut = int(len(rs) * 0.7)
        train += rs[:cut]
        test += rs[cut:]
    model = fit_logistic([r["features"] for r in train], [r["label"] for r in train])
    y = [r["label"] for r in test]

    def scores_of(f):
        return [f(r) for r in test]
    result = {"rows": len(ok), "errors": len(rows) - len(ok), "train": len(train), "test": len(test),
              "test_positives": sum(y), "methods": {}, "model": model.to_json(),
              "split": "per repo by time: oldest 70% train, newest 30% test"}
    for name, f in (("v1_weighted", lambda r: r["v1"]), ("v2_logistic", lambda r: model.score(r["features"])),
                    ("baseline_lines_changed", lambda r: r["lines"])):
        s = scores_of(f)
        pos = [v for v, l in zip(s, y) if l == 1]
        neg = [v for v, l in zip(s, y) if l == 0]
        result["methods"][name] = {"auc": M.auc(pos, neg), "precision_top10pct": M.precision_at_fraction(s, y, 0.10),
                                   "base_rate": sum(y) / len(y) if y else None}
    # per-feature AUC on the test rows (which signals separate inducing commits at all?)
    result["feature_auc"] = {k: M.auc([r["features"][k] for r in test if r["label"] == 1],
                                      [r["features"][k] for r in test if r["label"] == 0]) for k in FEATURES}
    # bootstrap interval for the AUC difference v2 - v1 (resample test rows)
    rng = random.Random(0)
    diffs = []
    for _ in range(1000):
        idx = [rng.randrange(len(test)) for _ in test]
        ys = [test[i]["label"] for i in idx]
        if 0 < sum(ys) < len(ys):
            a1 = M.auc([test[i]["v1"] for i in idx if test[i]["label"]], [test[i]["v1"] for i in idx if not test[i]["label"]])
            a2 = M.auc([model.score(test[i]["features"]) for i in idx if test[i]["label"]],
                       [model.score(test[i]["features"]) for i in idx if not test[i]["label"]])
            diffs.append(a2 - a1)
    diffs.sort()
    result["auc_v2_minus_v1_ci"] = (diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]) if diffs else None
    return result


def main(argv) -> None:
    rows_path = RES / "risk_rows.json"
    if "--reuse" not in argv or not rows_path.exists():
        rows = build_rows()
        rows_path.write_text(json.dumps(rows, indent=1))
    rows = json.loads(rows_path.read_text())
    res = evaluate(rows)
    (RES / "risk_summary.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "model"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
