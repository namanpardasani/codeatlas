NEW FLAGSHIP FEATURE: BLAST RADIUS. Read this whole message carefully. Do NOT write code yet.

FIRST:
a) Save this entire message verbatim as BLAST_RADIUS_PLAN.md in the repo root.
b) Update PROJECT_BRIEF.md: new one-line pitch "CodeAtlas predicts what your pull request will break, before you merge it." Keep the existing features as supporting features. Add a pointer to BLAST_RADIUS_PLAN.md.
c) Update CLAUDE.md so future sessions read BLAST_RADIUS_PLAN.md.
THEN reply with: (1) your summary in simple words, (2) risks, gaps and anything in the current codebase that blocks this, (3) a refined phase plan with effort estimates. Wait for me to say "go Phase 1". Do not commit or push unless I ask.

=====================================================
1. WHAT BLAST RADIUS IS
=====================================================
Given a code change (a GitHub PR URL, a commit SHA, or a raw diff) for an analyzed repo, CodeAtlas:
1. Finds exactly which functions, classes and files changed.
2. Propagates the impact through the code: who calls the changed functions, who imports the changed files, and which files historically change together with them (co-change), with confidence decaying by distance.
3. Ranks impacted files and symbols by risk, with a human-readable reason for each ("calls parseQuery() which changed", "changes together with router.js in 73% of past commits", "hotspot score 92").
4. Selects the minimal set of tests that should run for this change, instead of the whole suite.
5. Gives the change an overall risk score (0–100) with an explanation of the top contributing factors.
6. Suggests reviewers (people who most recently and most often touched the impacted code).
7. Posts all of this as a comment and a check run on the GitHub PR (GitHub App), shows it in the web UI as an animated "ripple" on the map, and exposes it to AI coding agents via MCP so an agent can check the blast radius BEFORE editing.

THE DIFFERENTIATOR: we prove it on history. We build a dataset of real regressions from popular open-source repos and measure how often Blast Radius would have flagged the code that later broke, and how many tests it would have needed to run. Every number on the README and my resume comes from this evaluation. Never invent or round up numbers.

=====================================================
2. HARD RULES
=====================================================
- The hosted service NEVER executes analyzed code (unchanged from before). Static analysis + git history only.
- Exception, clearly separated: the OFFLINE evaluation harness may run a project's tests ONLY inside a locked-down Docker container (no network, CPU/memory/time limits, read-only source mount, non-root user) and ONLY on the specific open-source repos in our dataset, to collect ground truth. This code lives in /eval and never runs in the web service. Explain this boundary in NOTES.md.
- Core Blast Radius must not need an LLM (fast, free, deterministic). An LLM may only write an optional plain-English summary of an already-computed result, cached by input hash, and capped per day.
- Free tier only. Tell me before anything could cost money.
- Small, commit-sized steps. CHECKPOINT after each step. Explain concepts simply before building them, then quiz me after each phase (3–5 interview-style questions) and wait for my answers.
- Parts marked [ME] are written by me. Create a clear stub with the interface, docstring, test cases and fixtures, then STOP and let me write it. You may write a reference implementation ONLY in tests/reference/ to cross-check mine, and only after I've written my version.

=====================================================
3. PHASES
=====================================================

PHASE 1: Function-level call graph (precision upgrade)
- Extend the tree-sitter pipeline (TS/JS + Python) to extract call sites inside each function: callee name, receiver/qualifier (obj.method, module.fn), line.
- Resolve calls to symbols with confidence levels: exact (same file / explicit import), probable (imported module + matching name), weak (name-only match across repo). Store confidence on each edge; never pretend weak edges are exact.
- Handle: methods on classes, re-exports, default exports, Python `from x import y as z`, relative imports, dynamic calls (mark unresolved).
- Tables: call_edges(repo_id, caller_symbol_id, callee_symbol_id, confidence, line), unresolved_calls(...). Indexes for both directions.
- Also build the reverse index (who calls this symbol) and keep the file import graph from Day 3.
- Tests: fixture repos with known call graphs, including tricky cases. Report precision/recall of call edges on fixtures.
CHECKPOINT 1.

PHASE 2: Diff to changed symbols
- Inputs: PR URL (public GitHub, fetch the diff via API, validate URL strictly), commit SHA in an analyzed repo, or raw unified diff upload (size-limited).
- Parse the unified diff into changed line ranges per file (handle added, deleted, renamed, binary, mode-only changes).
- Map line ranges to symbols using the AST of BOTH the old and new versions (a deleted function is a change too; a moved function is not a semantic change if its body is identical: detect by normalized-body hash).
- Classify each change: signature change, body change, new symbol, deleted symbol, comment/whitespace-only (ignored), config/non-code file.
- [ME] The function that maps diff hunks to symbols (start/end line overlap logic, including old-side vs new-side line numbers).
CHECKPOINT 2.

PHASE 3: Impact propagation + co-change
- Co-change model from git history (bounded window, e.g., last 500 commits or 12 months): for file pairs (and symbol pairs where possible), support and confidence (P(B changes | A changes)), ignoring huge commits (e.g., > 50 files, which are usually refactors or formatting) and lockfiles.
- Impact graph = reverse call edges (weighted by confidence) + reverse import edges + co-change edges (weighted by confidence).
- [ME] The propagation algorithm: start from changed symbols with score 1.0; propagate along reverse edges with per-edge weights and a decay per hop (e.g., 0.6), max depth (e.g., 4), keep the max score per node (or noisy-OR; I will decide and justify), and record the PATH that produced each score so we can explain it.
- Output: ranked impacted symbols and files with score, distance, edge types used, and the explanation path.
- Performance target: under 2 seconds for a typical PR on a repo with 2,000 files. Measure it.
CHECKPOINT 3.

PHASE 4: Test impact analysis (test selection)
- Detect test files and test functions (pytest conventions, Jest/Vitest/Mocha conventions, __tests__, *.test.*, *.spec.*, tests/ folders).
- Map each test to the symbols/files it reaches statically (imports + calls, transitive within a depth limit).
- Selected tests = tests whose reachable set intersects the impact set above a score threshold, ranked by score. Always include tests in files that changed. Report "N of M tests selected (X%)".
- Safety fallbacks: if the change touches config, build files, global setup/fixtures, or if too much is unresolved, say "run full suite" with the reason, instead of guessing.
CHECKPOINT 4.

PHASE 5: Change risk score
- Features per change: number of changed symbols, signature changes, size of impact set, max and sum of hotspot scores touched, centrality (PageRank) of changed files, churn of touched files, whether changed code sits in a cycle, test proximity (do selected tests exist?), co-change surprise (files usually changed together but missing from this PR), author's prior commits to these files.
- v1: a transparent weighted score. [ME] I will choose the weights and justify them.
- v2 (after Phase 7 has data): train a small logistic regression on the historical dataset to predict "this commit later needed a bug fix", using a TIME-BASED split (train on older commits, test on newer) to avoid leakage. Compare v1 vs v2 honestly (AUC, precision at top 10%). Keep whichever is better and explain why.
- Output: score 0–100, label (low / medium / high), top 3 contributing factors in plain words, and "missing co-changes" warnings ("router.js usually changes with this file but isn't in this PR").
CHECKPOINT 5.

PHASE 6: Surfaces (API, UI, MCP, GitHub App)
- API: POST /repos/:id/blast-radius { pr_url | commit_sha | diff } returns job id; GET result. Cache by (repo commit, diff hash).
- UI "Blast Radius" tab:
  - Input: paste PR URL or diff.
  - Hero: the map with the changed nodes in vermilion and an expanding RIPPLE animation spreading outward hop by hop to impacted nodes (rings expand, impacted nodes light up in order of distance, colour intensity = score). This animation has a job: it shows how impact travels. Respect reduced motion.
  - Risk gauge with the score and top factors; "missing co-changes" warning card.
  - Ranked impact list with the explanation path for each item (click to highlight the path on the map and open the code).
  - Selected tests list with "N of M (X%)" and a copyable command (e.g., pytest -k / vitest filter).
  - Suggested reviewers.
  - Optional cached plain-English summary.
- MCP tools: get_blast_radius(repo, diff_or_ref), suggest_tests(repo, diff_or_ref), check_change_risk(repo, diff_or_ref). Descriptions should tell agents to call these BEFORE editing shared code. Read-only, repo-scoped, output size limits.
- GitHub App (public repos for the demo; verify current GitHub docs for app setup and permissions):
  - Minimal permissions: pull requests read & write (comments), checks write, contents read, metadata read.
  - Webhook on pull_request opened/synchronize; verify the webhook signature (HMAC) on every request; idempotent processing per (PR, head SHA); queue the work.
  - Post/update ONE comment per PR (edit instead of spamming) with: risk score + label, top factors, impacted modules table (top 10), missing co-changes, selected tests with command, suggested reviewers, and a link to the interactive ripple view.
  - Create a check run (neutral, never block merges) with a summary.
  - Never log tokens; rate limit per installation; handle repos that aren't analyzed yet (trigger analysis, then post).
CHECKPOINT 6.

PHASE 7: THE EVALUATION (most important; resume numbers come from here)
Dataset (in /eval, reproducible with one command):
- Pick 5 popular open-source repos in our supported languages (e.g., 2–3 Python, 2–3 JS/TS), with good test suites and clear history. Propose candidates and justify; I approve the list.
- Find bug-fixing commits: commit messages matching fix/bug/regression/issue patterns AND, where possible, linked to closed issues labeled bug. Exclude merges, huge commits, docs/test-only changes, and dependency bumps.
- [ME] Find bug-INDUCING commits with the SZZ approach: for each line deleted or modified by the fix, git blame (ignoring whitespace and moves) to find the commit that last touched it before the fix; filter out commits older than the fix's issue report date and cosmetic changes. I will implement the core SZZ logic; you scaffold the git plumbing and tests.
- Manually validate a random sample (I'll review ~40 pairs with your help) and report the estimated SZZ precision. Keep only the validated-quality subset for headline numbers if the noise is high.
- Target size: ~200 (inducing commit, fixing commit) pairs total; fewer is fine if quality is better. Report the real count.

Experiment, for each pair:
- Run Blast Radius on the INDUCING commit, using only the repo state and history available at that time (no future leakage: analysis and co-change built from history BEFORE the inducing commit).
- Ground truth "broke here": the files/symbols modified by the FIX commit, plus the test files changed or added by the fix.
- Metrics: recall@5 / @10 of fix-touched files in the ranked impact list; symbol-level recall where possible; MRR; test selection ratio (selected / total tests); "would the fix's test have been selected?" rate; risk score AUC of inducing commits vs a random sample of non-inducing commits from the same period.
- Baselines (to prove the method matters): (a) changed files only, (b) same-folder files, (c) file import graph only, (d) co-change only, (e) full Blast Radius (call graph + imports + co-change). Plus ablations removing each component.
- Optional ground truth via coverage: for 1–2 repos, run the test suite once with coverage inside the locked-down container to build a real test-to-code map, then compare our static test selection against it (precision/recall of selected tests). Clearly labelled, offline only.
- [ME] The metric functions.

Outputs:
- eval/results/*.json and docs/BLAST_RADIUS_EVAL.md with methodology, dataset stats, a results table, baseline and ablation tables, charts, failure analysis (categorize misses: dynamic dispatch, config-driven behaviour, cross-language, SZZ noise), and honest limitations.
- A "Replay" page in the UI: pick a real historical regression from the dataset and watch Blast Radius run on the inducing commit, then reveal where the bug actually appeared. Pick 3 good, honest examples (including one miss, with the explanation).
- Update README headline numbers from the results ONLY.
CHECKPOINT 7.

PHASE 8: Finish
- Benchmarks: time and memory per PR on small/medium/large repos; record in docs.
- Security review of new surfaces: webhook verification, diff upload limits, PR URL validation (SSRF), token handling, MCP output limits, prompt injection if the LLM summary is used (treat repo content as data).
- Tests for every phase; CI green.
- NOTES.md: architecture of Blast Radius, all decisions and tradeoffs, "what happens if X fails", why SZZ, why time-based splits, limitations, and 20 interview Q&As specific to this feature.
- Resume bullets using only measured numbers, plus a 2-minute verbal pitch and a 60-second demo script (Replay page + PR comment + ripple map).
- Final quiz: 10 questions across call-graph resolution, propagation, co-change, test selection, SZZ, leakage, metrics and baselines. Wait for my answers.

=====================================================
4. CONCEPTS I MUST BE ABLE TO EXPLAIN
=====================================================
Call graph construction and why static resolution is imperfect; reverse dependency propagation with decay; co-change (association rules: support, confidence) and why it catches what static analysis misses; test impact analysis and safe fallbacks; SZZ algorithm and its noise; data leakage and time-based splits; recall@k, MRR, AUC; baselines and ablations; why we never block merges on a heuristic.

=====================================================
5. ORDER WITH THE REST OF THE PLAN
=====================================================
Blast Radius phases come BEFORE the design pass. Then the design pass (paper atlas) styles the Blast Radius tab and Replay page too.
