# CodeAtlas Notes

## Architecture
- Monorepo: `apps/api` (Node/Express/TS), `apps/web` (React/Vite), `workers/analyzer` (Python 3.12), `db/migrations` (plain SQL).
- Infra via Docker Compose: Postgres 16 + pgvector (host port 5433), Redis 7 (host port 6380). Ports bind to 127.0.0.1 only.

- Flow: web -> POST /repos (API validates URL, upserts repo, inserts job row, XADD to Redis stream `analysis:jobs`) -> worker (XREADGROUP, group `workers`) clones, inventories, upserts `files`, updates job row and PUBLISHes to `job:<id>:events` -> API SSE `/jobs/:id/events` relays to browser. Job row is the source of truth; the stream message only wakes a worker.
- Ports: API 4000, web 5173 (Vite proxies `/api` to the API), Postgres 5433, Redis 6380.

- Parser layer (`workers/analyzer/analyzer/parsing/`): `LanguagePlugin` per language (`js_ts.py` for TS/TSX/JS, `python_plugin.py`), registry by file extension in `__init__.py`, `parse_source(path, bytes) -> ParseResult(symbols, imports, exports, status, error)`. In the pipeline, parsing runs inside `SandboxedParser` (a child process).
- New tables (migration 002): `symbols`, `imports_raw` (imports exactly as written, unresolved), plus `files.parse_status/parse_error/exports`.
- Parsing stage: cloning 5 -> inventory 30 -> saving 45 -> parsing 50..90 -> done 100.
- UI: all styling in `apps/web/src/index.css` (`@theme` tokens) and `components/ui/*`; feature panels use only semantic classes.

## Decisions and tradeoffs
- tree-sitter: manual tree WALK for symbols and JS/TS imports (need parent/export context; require()/import() can appear anywhere); QUERIES are the natural fit for flat "find all X" patterns, so the Python import extraction (user-written TODO) is a query exercise.
- Parse in a child process, not in-process: the Python binding has no parse timeout and native code can hang/segfault on hostile input. Parent kills on timeout, survives crashes, records a per-file failure.
- Pinned `tree-sitter==0.25.2`: 0.26.0 segfaulted on a normal real file (sindresorhus/p-limit `test.js`). Found because the sandbox contained it and the job reported `parser process crashed`.
- Idempotency for parse output = delete the repo's symbols/imports and re-insert in ONE transaction (+ UNIQUE (file_id, idx)). Simple and correct; Day 7 incremental re-analysis will replace this with per-changed-file updates.
- `symbols.parent_name` is text, not an FK: it names the enclosing class/function; nested/anonymous cases make a row FK brittle.
- Python "exports" = `__all__` if present, else public (non-underscore) top-level names.
- SSE (not Socket.IO): progress is one-way server->client; simpler, works through the Vite proxy.
- URL validation happens twice (API and worker): the worker never trusts queue contents.
- File-count limit raises an error rather than silently truncating (a partial analysis would mislead).
- TypeScript pinned to 5.9 (TS 7's native binary segfaulted on this WSL box); vitest/esbuild/rolldown also crashed until node_modules was reinstalled (damaged native binaries).
- Node API + Python worker; worker writes analysis results directly to Postgres, so schema is plain SQL migrations (not Prisma, which can't cleanly own pgvector/tsvector).
- Queue: Redis Streams (consumer group) instead of BullMQ, because BullMQ's Redis format is Node-specific. Job state lives in `analysis_jobs`; progress also via Redis pub/sub -> SSE.
- Python 3.12 via uv (3.14 is too new for some ML/tree-sitter wheels; to be verified on Day 2).
- Ports 5433/6380 chosen because FlagForge containers already use 5432/6379.

## What happens if X fails
- A file has syntax errors: tree-sitter still returns a tree with ERROR nodes; we extract what we can, `parse_status='partial'`, `parse_error='syntax error near line N'`.
- A file is huge/minified: skipped (`parse_status='skipped'`) before parsing (512 KB cap; avg line length > 1000 bytes).
- A parse hangs: killed after PARSE_TIMEOUT_S (10s); file marked `failed: parse timed out`; a fresh child process takes over; job continues.
- The native parser segfaults: child dies, parent sees EOF, marks `failed: parser process crashed`, restarts child; job continues.
- Re-running a job: parse output is replaced atomically; counts stay identical (tested 3x against Postgres).
- Docker storage goes read-only / image layer corrupt (`exec format error`): symptom of Docker Desktop disk write errors. Fix: restart Docker Desktop, `docker rmi` the bad image, re-pull. Avoid "Purge data" (wipes other projects' volumes).

- Worker crashes mid-job: message stays pending (un-acked) in the stream; another worker XAUTOCLAIMs it after CLAIM_IDLE_MS; `attempts` is incremented per start and capped at MAX_ATTEMPTS so a poison job can't loop forever. Upserts on (repo_id, path) make re-runs safe.
- Redis down at submit time: job row exists with status `queued` but no stream message; a future sweeper can re-enqueue stale `queued` rows (not built yet).
- Malicious/huge repo: clone has a time limit and a size cap polled during the clone; hooks disabled, symlinks not materialized, submodules not fetched, code never executed.
- Browser disconnects from SSE: job continues; reconnecting sends current row state first, then live updates.
- XREADGROUP block longer than the client socket timeout looks like a connection failure; socket_timeout (30s) > block (5s).

## Interview Q&A
- What is a syntax tree? A tree of nodes (function_definition, import_statement, ...) with exact source positions, produced by a parser; nodes have named fields (e.g. `name`, `parameters`, `body`).
- Why tree-sitter over regex? Regex can't handle nesting, strings/comments or multi-line constructs; tree-sitter is incremental, gives positions, and recovers from syntax errors with partial trees.
- How do you handle syntax errors? Keep the partial tree, extract valid parts, flag the file `partial` with the first error line.
- Query vs walk? Queries: declarative, concise for flat patterns. Walk: needed when logic depends on ancestors/siblings (class membership, export wrappers, arrow functions assigned to names).
- How is re-running idempotent? Replace-in-one-transaction + unique (file_id, idx); a crash mid-way rolls back.
- Why a child process for parsing? Native code with no timeout API; isolation gives timeouts and crash containment.
- Why a queue instead of doing work in the request? Clone+parse take seconds to minutes; the API must return a job id immediately and stay responsive.
- Why plain SQL migrations, not Prisma? Python worker also writes to the DB; Prisma can't cleanly own pgvector/tsvector.
- What makes the job idempotent? Unique (repo_id, path) + ON CONFLICT upsert + delete of vanished files in one transaction.
- How do you stop SSRF? Allowlist of exactly https://github.com/<owner>/<repo>, no userinfo/port/query, repo name can't start with `-` (git option injection), re-validated in the worker, protocol.allow=never except https.

## Progress log
- 2026-10-16 Day 1, Step 1: monorepo folders, docker-compose.yml, .env.example. Postgres+pgvector (0.8.7) and Redis healthy.
- 2026-10-16 Day 1 complete: schema + migrate.sh, Express API (POST /repos, GET /jobs/:id, SSE), Python worker (Streams, safe clone, inventory), React progress UI. Verified end to end on octocat/Hello-World. 21 API tests + 22 worker tests pass.
- 2026-10-16 Day 2 complete: parser plugins (TS/TSX/JS symbols+imports+exports, Python symbols+exports), sandboxed parsing, migration 002, parsing stage, file list + symbol/import UI, token-based UI components. Python import extraction left as TODO stub with 3 xfail tests (user writes it). Verified on sindresorhus/p-limit (6 files, 42 symbols). Found and worked around a tree-sitter 0.26.0 segfault (pinned 0.25.2).
