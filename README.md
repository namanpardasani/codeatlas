# CodeAtlas

Codebase intelligence for GitHub repositories: dependency graph and cycles, hotspots, hybrid code search, cited
answers with a citation verifier, generated documentation, incremental re-analysis, and an MCP server for AI agents.

Project context: [PROJECT_BRIEF.md](PROJECT_BRIEF.md). Notes and decisions: [NOTES.md](NOTES.md).
MCP setup: [docs/MCP.md](docs/MCP.md). Evaluation: [docs/EVAL.md](docs/EVAL.md).

## Measured results

All numbers come from stored evaluation runs (see [docs/EVAL.md](docs/EVAL.md) for method, run ids and caveats).
The 50 evaluation questions were written by an AI (the one that built the system), not by a human maintainer, and the
sample is small; treat these as indicative, not as a benchmark.

| What | Result |
|---|---|
| Retrieval, hybrid search over AST chunks, 32 dev questions (4 repos) | MRR 0.481 → 0.658, recall@5 0.641 → 0.859 after the fixes |
| Same, 11 held-out questions not used to pick the fix | MRR 0.364 → 0.542, recall@10 0.682 → 0.773 |
| AST chunks vs fixed-size chunks (43 questions, hybrid) | no clear winner: hit@5 0.674 vs 0.581, MRR 0.451 vs 0.510 |
| Cross-encoder rerank | did not help (MRR 0.457 vs 0.451) |
| Dependency-edge precision / recall (104 verified edges, 4 repos) | 0.945 → 1.000 / 1.000 (easy cases) |
| Incremental re-analysis, psf/requests, 5-file change | 1.7 s vs 238 s cold full run (-99%), vs 3-4.6 s warm full run (-45-64%) |
| Answer quality (local 1.5B model) | not reported: the free local judge failed; see EVAL.md |
