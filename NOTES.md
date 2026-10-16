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

- Resolution layer (`analyzer/resolve/`): `js.py` (TS/JS), `python.py`, `jsonc.py` (tsconfig parsing); `resolve_imports()` returns per-import `Resolution(status internal|external|unresolved, targets, package, reason)`. Stored on `imports_raw` (migration 003). Pipeline stage "resolving" (92%).
- Graph layer (`analyzer/graph/`): `types.py` (Edge, DependencyGraph), `builder.py` + `cycles.py` are USER-WRITTEN TODO stubs, `reference.py` is a networkx reference used only to cross-check in tests.

## Decisions and tradeoffs
- Never guess: an import that looks internal but matches no file is `unresolved` with a reason (shown in the UI), not silently dropped or mapped to a "closest" file. Unresolved rate is itself a quality metric for the eval.
- External packages (npm, Node builtins, Python stdlib/third-party) are a separate list (`resolution='external'`, `package`), NOT graph nodes: they are not our code, would swamp the graph (react imported by 300 files), and cannot form cycles with our files.
- Python `from pkg import name`: edge to `pkg/__init__.py` AND to `pkg/name.py` if `name` is a submodule (otherwise the real dependency on the submodule would be missed).
- `./a.js` imported from TS means `a.ts` (TS ESM convention): try the TS twin first. If only a.js exists, resolve to it. We resolve `./index.js` to the real `index.js` even when `index.d.ts` exists (TypeScript would pick the .d.ts) because the graph should point at implementation files.
- tsconfig: nearest config up the tree; `extends` (relative) followed up to 5 levels; `paths` relative to `baseUrl` if set else the config's dir; longest-prefix pattern wins; Vite-style solution configs (`references`) are followed. NOT supported: `extends` from packages, package.json `exports`/`imports` (#), `main` pointing at build output (we fall back to src/index).
- Monorepo workspace packages: `package.json` name -> directory, resolved via source/module/main/types then src/index, index.
- Python import roots: repo root, parent of every top-level package (src layouts), src/, lib/, plus the importing file's own directory (scripts import siblings via sys.path[0]). Regular package beats same-named module.
- Cycles are SCCs of size >= 2 (self-imports dropped); output deterministic; algorithm must be iterative (5,000-deep chains in tests).
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
- Import cannot be resolved (typo, generated file, path alias we don't understand, file ignored/too large): recorded as `unresolved` + reason; the edge is simply absent from the graph; job continues.
- tsconfig is malformed/unreadable: JSONC parse returns None; we proceed without aliases (alias imports then show as external/unresolved) instead of failing.
- Circular `extends` in tsconfig: cycle guard + depth limit 5.
- Python relative import above the repo root: `unresolved: beyond the repository root`.
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
- Hard cases in import resolution? Extension-less imports and directory index files; TS ESM `.js`->`.ts`; tsconfig paths/baseUrl/extends/references; monorepo workspace packages; Python src layouts, relative levels, `from pkg import submodule`, namespace packages, stdlib vs third-party.
- Why not resolve everything by guessing? A wrong edge silently corrupts every downstream metric (cycles, centrality, hotspots). A recorded failure is measurable and fixable.
- Why exclude external packages from the graph? Not our code; would dominate fan-in; cannot create cycles with our files; kept as a separate list for a dependency report.
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
- 2026-10-16 Day 3 steps 1-2: import resolution (TS/JS + Python) stored and shown in UI; verified on p-limit (4 internal, 20 external, 0 unresolved). Graph scaffold ready (types, contracts, fixtures, networkx reference, 85 skipped tests waiting for the user's build_graph + find_cycles). PAUSED: steps 3-6 (metrics, storage/API, React Flow UI) wait for the user's implementation.
