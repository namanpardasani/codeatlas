# Resume bullets (only numbers produced by our runs)

Pick 3-4. Wording is for a project entry; keep the caveats if asked. Sources: docs/BLAST_RADIUS_EVAL.md,
eval/results/*.json, docs/EVAL.md.

**CodeAtlas: predicts what a pull request will break before it is merged** (TypeScript, Python, PostgreSQL/pgvector,
Redis, React, MCP, GitHub Apps)

- Built **Blast Radius**: maps a PR/commit/diff to the exact functions it changes (old- and new-side ASTs, body
  fingerprints; 1,764/1,764 real file patches reproduced byte for byte), propagates impact over a function-level call
  graph, imports and git co-change with per-step explanations, selects tests and scores risk; median **0.16-0.70 s per
  change** with a cached base (1.1-4.0 s cold) on 37-275-file repos, 0.14 s per change on Django's 2,978 code files.
- Evaluated it honestly on **477 real regressions** mined with SZZ from 5 OSS repos, with leakage-free replays (history
  before the inducing commit only), bootstrap intervals, held-out splits and ablations: on hand-validated pairs it ranks the
  later-fixed file higher than a changed-files baseline (**MRR 0.831 vs 0.670**); test selection runs a **median 6% of the
  suite** yet includes the fix's test file in **70%** of cases (vs 19% for name matching). Also reported where it does not
  win (beyond-the-diff ≈ same-folder heuristic; risk AUC 0.71 vs 0.74 for diff size alone).
- Built a function-level call graph for TS/JS/Python (imports, re-exports, default/CommonJS exports, inheritance, type
  hints) with honest confidence levels; audited real edges by hand (exact 22/22, probable 14/14 correct) and fixed 6
  failure modes found in the audit.
- Shipped it on four surfaces: a GitHub App (HMAC-verified webhooks, idempotent per head SHA, one edited PR comment and a
  neutral check run), an animated "ripple" map UI, a Replay page of real past regressions (including a miss), and 3 MCP
  tools agents call before editing; 929 automated tests (811 worker, 86 API, 32 MCP).

Earlier, supporting features:
**CodeAtlas: codebase-intelligence platform** (TypeScript, Python, PostgreSQL/pgvector, Redis, React, MCP)

- Built an end-to-end codebase analyser: tree-sitter parsing (TS/JS/Python), import resolution, dependency graph with cycle
  detection (Tarjan SCC), PageRank and an explainable hotspot score; processed `psf/requests` (124 files, 1,213 chunks) end to end.
- Designed incremental re-analysis with content-hash diffing and rename detection, proven equivalent to a full re-analysis by
  22 tests including randomised edit sequences; a 5-file change on `psf/requests` re-indexes in **1.67 s vs 238 s** for a
  full run with a cold vector cache (**3.06 s** with a warm cache).
- Implemented hybrid code search (AST-aware chunks, bge-small embeddings, pgvector HNSW + Postgres full-text, Reciprocal Rank
  Fusion) and a RAG chat whose citations are verified against the retrieved code; refuses weak evidence before calling the LLM.
- Built an evaluation harness (retrieval variants, recall@k / MRR with bootstrap intervals, graph precision/recall, held-out
  split); using its failure analysis, a source-first ranking change raised MRR **0.481 → 0.658** (dev) and **0.364 → 0.542**
  (held-out 11 questions), and an import-resolution fix raised dependency-edge precision **0.945 → 1.000** on 104 verified edges.
  (Questions were AI-authored; reported with that caveat.)
- Shipped a read-only **MCP server** (6 tools, stdio + API-key HTTP, repo-scoped access, read-only database role) and verified it
  from Claude Code; hardened the platform (OAuth login with PKCE, per-user quotas, strict clone allowlist, sandboxed parsing,
  security review with ranked findings).

## Numbers still missing (do not claim these yet)

| Missing | Why it matters | How to get it |
|---|---|---|
| Human-written evaluation questions and a human-graded answer-quality score | all quality numbers rest on AI-authored questions; there is no trustworthy answer-accuracy number | grade `eval/spotcheck.csv` (15 answers); write ~20 questions yourself |
| Uptime, real users, stars | the read-only demo is live at https://codeatlas-demo.onrender.com (free tier, sleeps when idle); no usage numbers exist yet | check the Render and GitHub dashboards after some weeks |
| Larger-repo scaling (largest analysed: 124 files) | "handles large repos" is unproven | analyse a 1,000-5,000 file repo and record time and memory |
| Query latency under load / p95 | only a single-user ~15 ms/query figure from Day 5 exists, not re-measured | run a small load test |
| Cost per analysis / per answer | budget is zero by design, but unmeasured in tokens for hosted LLMs | log tokens with a free-tier provider |
| Answer accuracy of a stronger model | the local 1.5B model's answers were mostly weak (4 of 15 sampled scored 0 on correctness and groundedness, graded by the author) | rerun `answers` with a better free-tier model and re-grade |

## Blast Radius numbers still missing

| Missing | How to get it |
|---|---|
| Human (maintainer) validation of the SZZ pairs | review `eval/blast/validation.json` yourself; the current verdicts are AI-made |
| Coverage-based test-selection ground truth | run 1-2 suites with coverage in a locked-down container (planned, not built) |
| Real PRs commented on by the GitHub App, and reactions to them | create the App (docs/DEPLOYMENT.md) and install it on a repo you own |

## 2-minute pitch

"Every team has merged a PR that looked small and broke something two folders away. CodeAtlas predicts that before the
merge. Give it a pull request: it works out exactly which functions changed, comparing the old and new syntax trees so
moves and comment edits are ignored. Then it walks backwards through the code: who calls those functions, who imports
them, and which files historically change together with them, because static analysis alone misses config and dynamic
dispatch. Everything it flags comes with the path that explains it. It also picks the tests to run, scores the risk, and
posts all of that as one comment and a non-blocking check on the PR, or answers an AI agent through MCP before the agent
edits shared code.

The part I am proudest of is the evaluation. I mined 477 real bug-introducing commits from five popular repos with SZZ,
replayed Blast Radius on each one using only the history before it, and compared it with baselines. I checked 70 pairs by
hand and found half of SZZ's labels were wrong, so I report numbers on the clean subset too. It ranks the buggy file higher
than a changed-files baseline on clean data, and its test selection runs a median of 6% of the suite while still catching
the fix's test 70% of the time. I also report where it does not win: beyond the diff it is about as good as a same-folder
heuristic, and diff size alone predicts risk as well as my model. Knowing that is what tells me what to build next."

## 60-second demo script

1. (0-15 s) Replay page: "This is a real flask commit from 2011. Blast Radius ran on it with only the history before it."
   Show the ranked list with reasons. Click **Reveal the fix**: `flask/app.py`, ranked first beyond the diff.
2. (15-30 s) Switch to the axios example and reveal: "And this is a miss: the bug was inside a class the change *used*;
   Blast Radius follows dependents, not dependencies. That is in the report."
3. (30-45 s) A repo's Blast Radius tab: paste a commit; the ripple spreads from the changed files hop by hop; open one
   impacted file and its explanation path; copy the pytest command.
4. (45-60 s) A PR with the GitHub App comment (risk, affected files, tests, reviewers), then Claude Code calling
   `suggest_tests` through MCP on a local diff.
