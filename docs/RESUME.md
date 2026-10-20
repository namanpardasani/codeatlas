# Resume bullets (only numbers produced by our runs)

Pick 3-4. Wording is for a project entry; keep the caveats if asked.

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
  security review with ranked findings). 765 automated tests (657 worker, 78 API, 30 MCP).

## Numbers still missing (do not claim these yet)

| Missing | Why it matters | How to get it |
|---|---|---|
| Human-written evaluation questions and a human-graded answer-quality score | all quality numbers rest on AI-authored questions; there is no trustworthy answer-accuracy number | grade `eval/spotcheck.csv` (15 answers); write ~20 questions yourself |
| Live demo URL, uptime, real users, stars | nothing is deployed yet | deploy Tier 1 of docs/DEPLOYMENT.md |
| Larger-repo scaling (largest analysed: 124 files) | "handles large repos" is unproven | analyse a 1,000-5,000 file repo and record time and memory |
| Query latency under load / p95 | only a single-user ~15 ms/query figure from Day 5 exists, not re-measured | run a small load test |
| Cost per analysis / per answer | budget is zero by design, but unmeasured in tokens for hosted LLMs | log tokens with a free-tier provider |
| Answer accuracy of a stronger model | the local 1.5B model's answers were mostly weak (4 of 15 sampled scored 0 on correctness and groundedness, graded by the author) | rerun `answers` with a better free-tier model and re-grade |
