> **UPDATE 2026-10-22: new flagship feature, Blast Radius.** New one-line pitch: **"CodeAtlas predicts what your pull request will break, before you merge it."** The full plan (phases, hard rules, evaluation) is in [BLAST_RADIUS_PLAN.md](BLAST_RADIUS_PLAN.md). Everything described below (map, hotspots, chat with citations, docs, MCP, eval) stays as supporting features, and Blast Radius builds on them.

You are my mentor, teacher and pair-programmer for one placement-focused project, working inside this empty repo. Read this whole message carefully; it is the full context.

FIRST, do only these setup actions, then stop:
a) Save this entire brief verbatim into PROJECT_BRIEF.md in the repo root.
b) Create a short CLAUDE.md that points to PROJECT_BRIEF.md, lists the working rules from section 13, and says to update NOTES.md at the end of every session.
c) Create an empty NOTES.md with headings: Architecture, Decisions and tradeoffs, What happens if X fails, Interview Q&A, Progress log.
d) Create a .gitignore suitable for Node, Python and Docker (include .env).
Do NOT commit or push anything unless I ask.

THEN reply with (1) a short summary in your own words of what we are building, (2) gaps, risks or contradictions you notice, and (3) a proposed Day 1 to Day 3 plan. Do NOT start building until I say "go".

==============================
1. ABOUT ME
==============================
- 3rd-year B.Tech student at a tier-3 college in India. Date is around October 2026. I want internships (summer 2027) and a good placement in 2027 at reputed product companies and startups. Most offers will come off-campus, so my projects need live links, measurable numbers and proof of real usage.
- Target roles: SDE / backend / platform / AI-infra engineer.
- I know JavaScript reasonably, and TypeScript and React from building my first project. I'm new to Python, tree-sitter/ASTs, vector search, RAG, MCP, Kafka and system design depth.
- I can ship fast with Claude Code (my first project took about 3 days). The risk is shipping faster than I understand. I must be able to explain every part in interviews. Teach me, quiz me, and make me write key logic myself.
- Budget: nothing beyond my existing Claude subscription. Hosting, databases and APIs should use free tiers or local tools. Verify current free-tier limits before relying on them. LLM API usage is billed separately from my subscription, so prefer free tiers or local models (e.g., Ollama) for development, cache aggressively, and tell me before anything could cost money.

==============================
2. MY 4-PROJECT PLAN (context)
==============================
1. FlagForge (DONE): multi-tenant feature-flag and experimentation SaaS. React + TypeScript + Tailwind, Node/Express, Postgres/Prisma, Redis, Socket.IO, npm SDK, Docker, GitHub Actions.
2. CodeAtlas (NOW, this project).
3. TraceForge (next): OpenTelemetry-native observability platform (Kafka, ClickHouse, trace/metric/log ingestion, alerting, LLM/agent tracing). It will later monitor FlagForge and CodeAtlas.
4. NebulaDB (last): LSM-tree key-value store in Go (WAL, SSTables, Bloom filters, compaction, crash recovery, Redis protocol), written mostly by me.
Parallel all year: DSA about 1 hour a day, open-source PRs, mock interviews; internship applications start around January 2027.

==============================
3. PROJECT: CODEATLAS (AI codebase intelligence platform)
==============================
One-line pitch (updated 2026-10-22): CodeAtlas predicts what your pull request will break, before you merge it. See [BLAST_RADIUS_PLAN.md](BLAST_RADIUS_PLAN.md).

Supporting features (the original pitch): Paste a GitHub repo URL and get an interactive architecture and dependency map, auto-generated docs, complexity and technical-debt hotspots, and a chat that answers questions about the code with file-and-line citations. The analysis is also exposed as an MCP server so AI coding agents (such as Claude Code) can query it.

Why this project: it combines real static analysis (tree-sitter/AST), graph algorithms, RAG with a measured evaluation, a job pipeline, and MCP. Plain "chat with your repo" tools are common, so the differentiators are (a) real parsing and graph analysis, (b) tech-debt/hotspot scoring from complexity + git churn, (c) MCP server, (d) a published evaluation score. The demo must work in under a minute on a public repo, with a live link and a short video.

==============================
4. PIPELINE (what happens after a URL is submitted)
==============================
1. API validates the URL, creates a repo record and an analysis job, and returns a job id. UI shows live progress.
2. A background worker shallow-clones the repo (size and file-count limits, ignore vendored/binary/generated files, honor .gitignore).
3. Parsing: tree-sitter parses supported languages (start with TypeScript/JavaScript and Python; add more later). Extract files, symbols (functions, classes, methods), imports/exports and call references where feasible.
4. Graph: build a file-level dependency graph (nodes = files, edges = imports). Compute cycles (strongly connected components), fan-in/fan-out, "central" files (PageRank or betweenness), and module/folder clusters. Resolve imports carefully (relative paths, aliases, package imports).
5. Metrics: per function and file: lines, cyclomatic complexity, nesting depth, function length, parameter count, duplication (hashing of normalized blocks), comment ratio. From git history: churn (commits touching a file in the last N days), number of authors, last-modified date.
6. Hotspot score: combine complexity and churn (hotspot = complex AND frequently changed), plus penalties for cycles, high fan-in and missing tests (does a test file exist?). Define the formula explicitly, document it, keep it tunable.
7. Chunking and embeddings: split code at function/class boundaries using the AST (NOT fixed-size chunks), attach metadata (file, symbol, line range, language). Embed with a free/local embedding model, store in Postgres with pgvector. Also keep a lexical index (Postgres full-text) for hybrid search.
8. Docs generation: bottom-up summarization (function -> file -> folder/module -> repo overview), cached by content hash so unchanged files are never re-summarized.
9. Q&A (RAG): hybrid retrieval (vector + keyword), optional rerank, assemble context, call the LLM, return the answer with citations (file path + line range), and say "not found" when evidence is weak. Support streaming.
10. Incremental re-analysis: on re-submission, only re-process changed files (compare commit SHAs and file hashes).

==============================
5. TECH STACK
==============================
- Frontend: React + TypeScript + Vite + Tailwind CSS. React Flow (or D3) for the graph, file tree, code viewer with line highlighting, hotspot table, chat panel with citations.
- API: Node.js + Express + TypeScript, Zod validation, auth (JWT or GitHub OAuth), rate limiting.
- Analysis workers: Python (tree-sitter bindings, networkx for graph algorithms, custom or radon-style metrics). Workers consume jobs from a queue.
- Queue/progress: Redis (BullMQ on the Node side, or a simple Redis queue consumed by Python workers; decide and justify). Progress via SSE or Socket.IO.
- Database: PostgreSQL with pgvector. Migrations via Prisma on the Node side or plain SQL migrations if Python workers write directly; decide and justify.
- LLM: provider-agnostic interface so I can swap providers (free-tier hosted API for dev, Claude API optional later, Ollama locally). Embeddings: a local open model (small sentence-transformer/BGE) to avoid cost.
- MCP server: official MCP SDK (TypeScript or Python). Tools: get_architecture(repo), find_symbol(repo, name), get_dependencies(repo, file), get_hotspots(repo, limit), explain_file(repo, path), search_code(repo, query). Support stdio and HTTP.
- DevOps: Docker + Docker Compose (api, worker, postgres+pgvector, redis), GitHub Actions for tests and lint, free-tier deployment (verify current limits: e.g., Neon for Postgres+pgvector, Upstash for Redis, Render/Fly for API/worker, Vercel/Netlify for frontend). Free hosts may sleep, so also record a demo video.
- Testing: Vitest/Jest for Node, pytest for Python, plus the evaluation harness (section 7).

==============================
6. DRAFT DATA MODEL (review and improve; not final)
==============================
users(id, email, name, created_at)
repos(id, owner_id, url, name, default_branch, last_commit_sha, status, created_at)
analysis_jobs(id, repo_id, commit_sha, status[queued|running|done|failed], stage, progress, error, started_at, finished_at)
files(id, repo_id, path, language, size, content_hash, lines, complexity, churn_30d, authors, last_modified, hotspot_score)
symbols(id, repo_id, file_id, name, kind[function|class|method], start_line, end_line, complexity, params, signature)
dependencies(id, repo_id, from_file_id, to_file_id, kind[import|require|dynamic]) with indexes on (repo_id, from_file_id) and (repo_id, to_file_id)
chunks(id, repo_id, file_id, symbol_id, start_line, end_line, content, content_hash, embedding vector, tsv tsvector)
summaries(id, repo_id, target_type[symbol|file|folder|repo], target_ref, content_hash, summary, model, created_at)
chat_sessions(id, repo_id, user_id, created_at); chat_messages(id, session_id, role, content, citations JSONB, created_at)
eval_runs(id, repo_id, config JSONB, retrieval_score, answer_score, created_at)
Indexes: pgvector HNSW or IVFFlat on chunks.embedding; GIN on chunks.tsv; unique (repo_id, path) on files.

==============================
7. EVALUATION SUITE (key differentiator; do not skip)
==============================
- Choose 3 to 5 well-known open-source repos (mix of languages and sizes).
- Write about 50 questions with ground-truth answers and the correct file(s)/symbol(s), e.g. "where is request routing configured?", "which module handles auth?", "what depends on file Y?".
- Retrieval metrics: recall@k and MRR.
- Answer quality: rubric scoring by an LLM judge plus manual spot-checks; report citation accuracy (do cited lines support the claim?) and hallucination rate.
- Graph metrics: compare my dependency graph to ground truth on small repos (precision/recall of edges).
- Compare variants (fixed-size vs AST-aware chunks; vector-only vs hybrid; with/without rerank) and publish the table in the README. These numbers go on my resume.

==============================
8. CORE CONCEPTS I MUST TRULY UNDERSTAND
==============================
- Syntax trees and how tree-sitter queries extract symbols and imports.
- Directed graphs: cycle detection via strongly connected components (Tarjan/Kosaraju), centrality (PageRank/betweenness), topological ordering.
- Cyclomatic complexity and why complexity x churn finds risky code.
- Embeddings, cosine similarity, ANN indexes (HNSW vs IVFFlat), hybrid search, reranking, why AST-aware chunking beats fixed-size chunking.
- RAG failure modes (missing context, hallucinated citations, stale index) and how to evaluate them.
- Content-hash caching and incremental indexing.
- Job queues: retries, idempotency, progress reporting, handling huge or malicious repos (size limits, timeouts, never executing code, sandboxed cloning).
- MCP: servers, tools vs resources, how an agent calls them, and security (read-only, repo scoping, input validation).
- Security: never execute analyzed code, validate URLs (SSRF), limit clone size/time, encrypt tokens, rate limit per user, defend against prompt injection from repo contents.

==============================
9. PARTS I WILL WRITE MYSELF (you review; do not write first)
==============================
- Dependency graph builder and cycle detection.
- Hotspot scoring formula.
- AST-aware function/class chunking.
- Evaluation harness (metrics computation).
- (Optional) the import resolver for one language.
Everything else may be generated, but you must explain it and quiz me afterwards.

==============================
10. FEATURE PRIORITIES
==============================
Must have: repo submission, async analysis pipeline with progress, TS/JS and Python parsing, dependency graph visualization, hotspot report, file tree + code viewer, RAG chat with citations, Postgres + pgvector, Docker Compose, tests, deployed demo.
Should have: hybrid search, incremental re-analysis, doc generation, MCP server with 5-6 tools, evaluation suite with published scores, GitHub OAuth, rate limiting, CI.
Nice to have: architecture drift across commits, PR-impact analysis ("which modules does this diff affect?"), exportable Markdown docs, more languages, onboarding-guide generator, GitHub App that comments on PRs.

==============================
11. TIMELINE (about 8 to 10 days)
==============================
Day 1: repo setup, schema, Docker Compose, queue, clone + file inventory, progress UI skeleton.
Day 2: tree-sitter parsing (symbols + imports) for TS/JS and Python, stored in DB.
Day 3: dependency graph + cycle detection + central files (written by me), React Flow visualization.
Day 4: metrics + git churn + hotspot scoring (formula by me), hotspot UI.
Day 5: AST-aware chunking (by me), embeddings, pgvector, hybrid search.
Day 6: RAG chat with citations and streaming, refusal on weak evidence.
Day 7: docs generation with caching, incremental re-analysis.
Day 8: MCP server and tools; test it from Claude Code.
Day 9: evaluation suite and published scores; fix weaknesses it reveals.
Day 10: deployment, README with architecture diagram, demo video, NOTES.md, "can I explain everything?" review, resume bullets.

==============================
12. TARGET RESUME BULLETS (earn these with real numbers)
==============================
- Built an AI codebase-analysis platform that parses N languages with tree-sitter and generates dependency graphs, cycle reports and complexity x churn hotspot scores.
- Implemented AST-aware chunking and hybrid (vector + keyword) retrieval, reaching X% recall@5 and Y% citation accuracy on a 50-question eval set (vs Z% for fixed-size chunking).
- Exposed analysis through an MCP server with 6 tools, usable from AI coding agents.
- Async pipeline with incremental re-analysis cutting re-index time by X%; deployed with Docker and CI/CD.

==============================
13. HOW I WANT YOU TO WORK WITH ME
==============================
- Teach first, then build: explain the concept simply, show where each tool fits and why, then plan, then code.
- One small, commit-sized step at a time. Never dump the whole app.
- Ask me to write the key logic in section 9, then review my version.
- After each major piece, quiz me with 3 to 5 interview-style questions and correct my gaps.
- Keep NOTES.md updated at the end of each session: decisions, tradeoffs, "what happens if X fails" answers, interview Q&A, progress log.
- Be honest: push back on overkill, flag cost or free-tier risks, verify current library versions and limits instead of guessing.
- Flag security issues proactively (SSRF, malicious repos, token handling, prompt injection via repo contents).
- Keep explanations simple and concrete; I'm still learning Python, graphs, vector search and MCP.
- When I paste errors, explain the cause, not only the fix.
- Do not commit or push to git unless I ask.

==============================
14. WHAT I WANT FROM YOU RIGHT NOW
==============================
1. Do the setup actions (a) to (d) at the top.
2. Summarize the project back to me in simple words.
3. List gaps, risks and contradictions (especially: free LLM/embedding options, Python-vs-Node split, queue choice, import-resolution difficulty, repo size limits, prompt injection via repo content).
4. Propose a detailed Day 1 plan: setup steps, what to learn first, what Claude Code builds, and what I write myself.
5. Do NOT start coding until I say "go".
