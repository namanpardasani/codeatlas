# 10-minute "explain the project" (rehearse out loud)

**0:00 Problem and pitch (1 min).** Reading an unfamiliar repo takes days. CodeAtlas takes a public GitHub URL and gives you the
architecture, the risky files, searchable code and cited answers, and lets AI agents use the same knowledge through MCP.
Public repos only, zero budget, everything runs locally for free.

**1:00 The pipeline (2 min).** Browser → Express API → Redis stream → Python worker → Postgres. Walk one job: safe shallow clone
(hooks off, no symlinks, size/time limits) → inventory → tree-sitter parse in a sandboxed child process → resolve imports →
dependency graph and cycles (strongly connected components) → git history for churn → duplicates → hotspot score → chunk by AST →
embed with a content-hash cache → docs. Progress goes back over Redis pub/sub and SSE. The job row in Postgres is the source of truth;
the queue message just wakes a worker.

**3:00 Graphs and hotspots (1.5 min).** Edges are resolved imports, never guesses; unresolved imports are recorded with a reason. Cycles:
SCC, because the number of simple cycles can be exponential. Hotspot = complexity + churn + fan-in/centrality + cycles +
duplication + missing tests, each factor normalised, and the score returns its reasons so it is explainable, not a black box.

**4:30 Search and RAG (2 min).** AST-aware chunks keep a function whole and prepend its path and name. Hybrid retrieval:
pgvector HNSW for meaning, Postgres full-text for exact identifiers, fused by RRF (rank-based, so no score calibration).
Chat: refuse before calling the model if evidence is weak; delimit repo text as untrusted data; give the model no tools; then verify
every citation against the retrieved code and delete unsupported sentences.

**6:30 Incremental re-analysis and caching (1 min).** Content hashes decide added/modified/deleted/renamed. Global stages
(graph, hotspots) are always recomputed from stored + fresh data, which is why incremental equals full, tested. Vectors are cached by
hash of header + content: 5-file change 1.67 s vs 238 s cold full. Be honest that most of the saving is the vector cache.

**7:30 Evaluation (1.5 min).** 50 questions, 4 repos, written by AI (say so). Dev/held-out split; fixes chosen on dev only. Source-first
ranking lifted MRR 0.481 → 0.658 dev and 0.364 → 0.542 held-out; AST vs fixed chunking was a tie; rerank didn't help; the free local LLM judge
failed, so no quality score is claimed. Graph precision 0.945 → 1.000 after the `from . import x` fix.

**9:00 MCP, security, deployment (1 min).** MCP: six read-only tools, read-only DB role, repo-scoped keys, output sanitising. Security:
OAuth + quotas, SSRF allowlist, nothing from a repo is executed. Deployment: free tiers can't host the worker, so a read-only demo
on Render + Neon with pre-analysed repos, full pipeline via Docker Compose, plus a recorded video.

## Study questions (answer out loud, then check NOTES.md)

1. Why Tarjan SCC for cycles instead of enumerating cycles? What does a 11-file group mean?
2. Why do unresolved imports get recorded instead of guessed? What breaks if a wrong edge is stored?
3. Explain the hotspot score: what are the factors, why normalise, how are reasons produced?
4. What does the AST-aware chunker do that fixed windows don't, and what did our measurement actually show?
5. Why RRF instead of adding vector and keyword scores?
6. Walk through what makes a RAG answer "verified". What does the verifier remove, and what can it not catch?
7. Why refuse before calling the LLM, and how was the 0.70 similarity threshold chosen (and why is it fragile)?
8. How does incremental re-analysis stay equal to a full analysis? What are its known limitations (renames with edits)?
9. recall@k vs MRR: when do they disagree? Why bootstrap intervals with 43 questions?
10. Why did the held-out split matter, and what can't the numbers prove?
11. Why can't an LLM judge be trusted here? Name three biases and what we observed.
12. MCP vs a REST API; tools vs resources; stdio vs HTTP transports.
13. What are the prompt-injection paths in this system and the mitigations for each? What remains?
14. Walk through the clone safety measures: what would a malicious repo try, and what stops it?
15. Why can't the whole thing be hosted free, and what exactly works live? What is the fallback?
