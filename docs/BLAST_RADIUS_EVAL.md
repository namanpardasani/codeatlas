# Blast Radius: evaluation on real regressions

**Question:** if Blast Radius had been run on the commit that introduced a bug, would it have pointed at the code where
the bug was later fixed, which tests would it have selected, and would its risk score have flagged the commit?

Every number below comes from stored runs in `eval/results/` (`blast_summary.json`, `risk_summary.json`, per-pair files
`blast_*_pairs.json`). Nothing is rounded up. Reproduce with the commands at the end.

## Short answer

| Finding | Evidence |
|---|---|
| On the **cleanest data** (23 hand-confirmed pairs), Blast Radius ranks the buggy file higher than "changed files only" | MRR **0.831** vs 0.670, recall@5 0.946 vs 0.826; 95% interval of the MRR difference [0.05, 0.29], excludes 0 |
| On **all pairs** (477, noisier labels), the gain is small and not significant | MRR 0.757 vs 0.731 (difference interval [-0.01, 0.06]); recall@5 is *lower* (0.833 vs 0.878) |
| **Beyond the diff** (files the inducing commit did not touch, 48 pairs) it finds about 4 in 10 fix files in the top 10, like a simple same-folder heuristic | recall@10 **0.381** vs 0.414 (folder baseline); difference not significant |
| **Co-change** carries most of the beyond-the-diff signal; the call graph alone adds little at file level | without co-change: recall@10 0.257; calls only: 0.106 |
| **Max** combination beats noisy-OR clearly | all-pairs MRR 0.757 vs 0.633, interval of the difference [-0.15, -0.10] |
| **Test selection**: a median of **6%** of the suite still catches the fix's test file in **70%** of cases | 201 pairs with an existing fix test file; name-matching baseline: 19% |
| **Risk score**: separates bug-inducing commits from others (AUC 0.71), but **diff size alone does as well** (AUC 0.74) | 341 held-out commits, 120 inducing |

## Dataset

**Repositories** (pinned heads in `eval/blast/repos.json`): psf/requests, pallets/flask (Python), axios/axios,
expressjs/express (JavaScript), sindresorhus/got (TypeScript). Chosen for supported languages, real test suites and long
histories (1,788 to 6,495 commits).

**Bug-fixing commits.** Subject matches fix/bug/regression/crash/broken/incorrect/wrong/...; excluded: merges, typo/docs/CI/
lint/release/dependency commits, type-checker-only subjects (mypy, typing, annotations), commits over 10 files, and fixes
that modify no existing non-test source file. A fix must also make a **functional** change (Phase 2 change analysis: at
least one symbol whose code fingerprint changed, or module code beyond imports), which removes comment/docstring/`type:
ignore` "fixes".

**Bug-inducing commits (SZZ).** For each line the fix deleted or modified in a source file, `git blame -w -M -C` on the
fix's parent (whitespace ignored, moves and copies followed, blank and comment lines skipped, mass-formatting and huge
commits ignored via `--ignore-rev`). The inducing commit is the one owning the most blamed lines (ties: most recent).

**Splits.**

| Split | Pairs | Used | Mined | Purpose |
|---|---|---|---|---|
| development | 225 | 208 | 45 most recent fixes per repo | v1 run as pre-registered; v2 designed on it |
| test | 150 | 146 | next 30 older fixes per repo | judges v2 |
| test 2 | 125 | 123 | next 25 older fixes per repo | judges v3 (decided after test) |

"Used" excludes pairs whose fix touches no source file that existed at the inducing commit.

**Manual validation of SZZ** (`eval/blast/validation.json`; reviewer: Claude, an AI, judging from both diffs, **not a
human maintainer**):

| Sample | Correct | Unsure | Incorrect | Precision (strict / lenient) |
|---|---|---|---|---|
| 40 pairs from plain SZZ | 14 | 7 | 19 | 35% / 53% |
| 30 fresh pairs after the functional-change filter | 15 | 6 | 9 | **50% / 70%** |

Incorrect pairs, by cause (both rounds, 28): non-functional fix 9, the bug predates the blamed commit 6, external change
(e.g. urllib3 de-vendoring, Redis v4 API) 4, a move or rename was blamed 4, missing feature rather than a bug 2, only a
docstring was blamed 1, a later commit triggered the bug 1, new capability rather than a fix 1. Unsure (13): tangled
commits 7, possibly older origin 3, feature-like 2, missing feature 1. **Half the pairs are wrong or doubtful**, which is why results are also reported on
the 26 validated-correct pairs.

## Method

**No leakage.** For each pair, the snapshot, call graph and co-change model are built at the inducing commit's
*parent*, with history up to that parent only. The fix is used only as ground truth.

**Ground truth.** `truth`: existing non-test source files the fix modified. `beyond`: the subset the inducing commit did
not change. Test ground truth: test files (and test functions) the fix edited that existed at the inducing commit.

**Important structural bias.** SZZ blames lines inside the fix's files, so the inducing commit always touched at least
one of them. The "changed files only" baseline is therefore close to perfect by construction on `truth`. Only `beyond`
measures what propagation adds, and it is small (48 of 477 pairs).

**Methods.**
- Baselines: (a) changed files (most changed lines first); (b) changed files then same-folder files by churn;
  (c) import graph only; (d) co-change only.
- Blast Radius: calls + imports + co-change, max combination (v1, weights fixed before any result).
- Ablations: each component removed; weak calls removed; calls only; noisy-OR.
- Metrics: recall@k, hit@k, MRR, with 2,000-sample bootstrap intervals (resampling pairs) and paired intervals for
  differences.

**Pre-registration and tuning.** v1 was frozen before the first run, so all three splits are unseen data for it and are
pooled. v2 (churn tie-break) was designed on the development split and is reported on test + test 2. v3 (files of the
change always ranked first) was decided after test and is reported on test 2 only. Test selection (threshold 0.1) and
risk v1 weights were also fixed before evaluation.

## Results: ranking

v1, pooled over all splits (each cell: mean, 95% interval):

| Method | All pairs (n=477) MRR | R@5 | R@10 | Beyond the diff (n=48) MRR | R@5 | R@10 |
|---|---|---|---|---|---|---|
| (a) changed files | 0.731 [0.71, 0.76] | 0.878 | 0.914 | 0.000 | 0.000 | 0.000 |
| (b) same folder | 0.731 [0.71, 0.76] | 0.888 | 0.931 | **0.302** [0.20, 0.43] | 0.358 | **0.414** |
| (c) imports only | 0.755 [0.72, 0.79] | 0.830 | 0.892 | 0.150 | 0.221 | 0.278 |
| (d) co-change only | 0.757 [0.73, 0.79] | 0.833 | 0.893 | 0.204 | 0.182 | 0.227 |
| **Blast Radius (v1)** | **0.757** [0.73, 0.79] | 0.833 | 0.898 | 0.215 [0.13, 0.30] | 0.282 | 0.381 [0.26, 0.51] |
| − calls | 0.757 | 0.834 | 0.898 | 0.212 | 0.225 | 0.396 |
| − imports | 0.757 | 0.834 | 0.894 | 0.223 | 0.260 | 0.288 |
| − co-change | 0.754 | 0.831 | 0.891 | 0.156 | 0.173 | 0.257 |
| − weak calls | 0.757 | 0.833 | 0.898 | 0.214 | 0.282 | 0.381 |
| calls only | 0.754 | 0.829 | 0.886 | 0.092 | 0.106 | 0.106 |
| noisy-OR | 0.633 [0.60, 0.67] | 0.707 | 0.770 | 0.232 | 0.233 | 0.355 |

Validated-correct subset (23 usable pairs; beyond-the-diff n=1, not reported):

| Method | MRR | R@5 | R@10 |
|---|---|---|---|
| changed files | 0.670 [0.53, 0.80] | 0.826 | 0.913 |
| **Blast Radius (v1)** | **0.831** [0.70, 0.95] | **0.946** | 0.957 |
| noisy-OR | 0.716 | 0.815 | 0.859 |

Later variants (held-out only): v2 on test + test 2, all pairs MRR 0.740 vs v1 0.739 (difference interval [-0.03,
0.03]); v3 on test 2 identical to v2 (the reordering moved no ground-truth file). **Neither beat v1**, so v1 remains the
scoring; the product shows the change's own files first for readability, which has no measured effect.

**Reading it.** Blast Radius helps most at ordering the files of the change itself (which changed file is the risky
one). Beyond the diff, it is about as good as "same folder, most-churned first". Its advantage is that every item comes
with a reason, and the two could be combined (the folder edge, v2_folder, reached recall@10 0.604 on the 24 held-out
beyond pairs, but it was not pre-registered and needs a fresh test before it can be claimed).

## Results: test selection

Selection on the inducing commit; ground truth = existing tests the fix edited. Pooled over 475 pairs (the threshold was
fixed before any split was evaluated).

| Method | Selected (median / mean of suite) | Full suite requested | Fix's test file caught | Fix's test functions caught |
|---|---|---|---|---|
| Blast Radius, subset only (no fallback) | **6.1%** / 26.9% | 0% | **70.1%** (n=201) | 47.5% (n=36) |
| Blast Radius with safety fallback | 50% / 51.7% | 36% | 83.6% | 70.2% |
| name matching (`test_x.py` for `x.py`) | 0% / 3.5% | 0% | 18.9% | 14.8% |

The fallback ("run the full suite") fires mainly because inducing commits often touch build or dependency files
(`package.json`, `setup.py`), which every test depends on. When a subset is returned (123 pairs), it catches the fix's
test file 73.2% of the time.

## Results: risk score

Positives: 376 unique inducing commits; negatives: 752 random source-touching, non-inducing commits (2 per positive)
from the same repos and period (label noise: some negatives contain bugs SZZ never found, so AUCs are conservative). Split per
repo by time: oldest 70% train (787 rows), newest 30% test (341 rows, 120 positives).

| Model | AUC | Precision in top 10% | Notes |
|---|---|---|---|
| v1 hand-set weights | 0.707 | 0.676 | fixed before evaluation |
| v2 logistic regression | 0.727 | 0.676 | trained on the older 70%; AUC difference v2−v1 interval [-0.015, 0.053] |
| lines changed alone | **0.738** | 0.706 | baseline |

Single-feature AUCs: size 0.737, changed symbols 0.724, complexity 0.657, churn 0.643, centrality 0.628, API changes 0.620,
breadth 0.601; inexperience 0.550, missing co-change 0.530; import cycle 0.482 and "no tests" 0.467 carry no signal here.
**Decision:** v1 stays the default (v2 is not significantly better and needs a trained artifact; `BLAST_RISK_MODEL` can
enable it). The honest headline is that diff size is the strongest single predictor; the score's value is in its
explanation, not in beating size.

## Failure analysis

Of the 74 beyond-the-diff fix files: 28 were in the top 10, 27 were reached but ranked lower, 19 were never reached.
- **Never reached: the change depends on the buggy code.** Example (Replay page): axios bb5f9a5a wrapped fetch errors in
  `AxiosError`; the bug was inside `AxiosError`. Propagation follows dependents (callers, importers, co-changed files),
  not dependencies.
- **Reached but low: ties among importers.** Module-level changes reach every importer with the same score; the right
  one is often not first.
- **Dynamic and config-driven behaviour.** Calls through variables, plugin registries and config objects are invisible
  to static resolution (Phase 1 records them as unresolved).
- **SZZ noise.** About half the pairs are wrong or doubtful (validation above); the ranking cannot be right about a
  wrong ground truth.
- **Cross-language.** TypeScript declaration files (`index.d.ts`) changed with JavaScript sources are only linked
  through co-change.

## Limitations

- Five repositories; beyond-the-diff results rest on 48 pairs, with wide intervals.
- SZZ labels are noisy; the validation was done by an AI from diffs, not by maintainers; issue-linked fixes (closed bug
  issues) were not used, to avoid GitHub API rate limits.
- File-level metrics only; symbol-level recall is not reported.
- The optional coverage-based ground truth (running test suites in a locked-down container) was **not done**.
- Risk labels: non-inducing commits are not guaranteed bug-free.

## Reproduce

```bash
cd workers/analyzer
# clones of the pinned repos go to eval/blast/.repos (see eval/blast/repos.json)
uv run python -m analyzer.blast.evaluation mine --limit 45                 # dev pairs
uv run python -m analyzer.blast.evaluation mine --limit 30 --split test    # held-out
uv run python -m analyzer.blast.evaluation mine --limit 25 --split test2   # second held-out
uv run python -m analyzer.blast.evaluation run [--split test|test2] [--validated]
uv run python -m analyzer.blast.evaluation.report                           # eval/results/blast_summary.json
uv run python -m analyzer.blast.evaluation.risk_eval                        # eval/results/risk_summary.json
uv run python -m analyzer.blast.evaluation.replays                          # Replay page data
```
