# CodeAtlas Notes

## Architecture
- Monorepo: `apps/api` (Node/Express/TS), `apps/web` (React/Vite), `workers/analyzer` (Python 3.12), `db/migrations` (plain SQL).
- Infra via Docker Compose: Postgres 16 + pgvector (host port 5433), Redis 7 (host port 6380). Ports bind to 127.0.0.1 only.

- Flow: web -> POST /repos (API validates URL, upserts repo, inserts job row, XADD to Redis stream `analysis:jobs`) -> worker (XREADGROUP, group `workers`) clones, inventories, upserts `files`, updates job row and PUBLISHes to `job:<id>:events` -> API SSE `/jobs/:id/events` relays to browser. Job row is the source of truth; the stream message only wakes a worker.
- Ports: API 4000, web 5173 (Vite proxies `/api` to the API), Postgres 5433, Redis 6380.

## Decisions and tradeoffs
- SSE (not Socket.IO): progress is one-way server->client; simpler, works through the Vite proxy.
- URL validation happens twice (API and worker): the worker never trusts queue contents.
- File-count limit raises an error rather than silently truncating (a partial analysis would mislead).
- TypeScript pinned to 5.9 (TS 7's native binary segfaulted on this WSL box); vitest/esbuild/rolldown also crashed until node_modules was reinstalled (damaged native binaries).
- Node API + Python worker; worker writes analysis results directly to Postgres, so schema is plain SQL migrations (not Prisma, which can't cleanly own pgvector/tsvector).
- Queue: Redis Streams (consumer group) instead of BullMQ, because BullMQ's Redis format is Node-specific. Job state lives in `analysis_jobs`; progress also via Redis pub/sub -> SSE.
- Python 3.12 via uv (3.14 is too new for some ML/tree-sitter wheels; to be verified on Day 2).
- Ports 5433/6380 chosen because FlagForge containers already use 5432/6379.

## What happens if X fails
- Docker storage goes read-only / image layer corrupt (`exec format error`): symptom of Docker Desktop disk write errors. Fix: restart Docker Desktop, `docker rmi` the bad image, re-pull. Avoid "Purge data" (wipes other projects' volumes).

- Worker crashes mid-job: message stays pending (un-acked) in the stream; another worker XAUTOCLAIMs it after CLAIM_IDLE_MS; `attempts` is incremented per start and capped at MAX_ATTEMPTS so a poison job can't loop forever. Upserts on (repo_id, path) make re-runs safe.
- Redis down at submit time: job row exists with status `queued` but no stream message; a future sweeper can re-enqueue stale `queued` rows (not built yet).
- Malicious/huge repo: clone has a time limit and a size cap polled during the clone; hooks disabled, symlinks not materialized, submodules not fetched, code never executed.
- Browser disconnects from SSE: job continues; reconnecting sends current row state first, then live updates.
- XREADGROUP block longer than the client socket timeout looks like a connection failure; socket_timeout (30s) > block (5s).

## Interview Q&A
- Why a queue instead of doing work in the request? Clone+parse take seconds to minutes; the API must return a job id immediately and stay responsive.
- Why plain SQL migrations, not Prisma? Python worker also writes to the DB; Prisma can't cleanly own pgvector/tsvector.
- What makes the job idempotent? Unique (repo_id, path) + ON CONFLICT upsert + delete of vanished files in one transaction.
- How do you stop SSRF? Allowlist of exactly https://github.com/<owner>/<repo>, no userinfo/port/query, repo name can't start with `-` (git option injection), re-validated in the worker, protocol.allow=never except https.

## Progress log
- 2026-10-16 Day 1, Step 1: monorepo folders, docker-compose.yml, .env.example. Postgres+pgvector (0.8.7) and Redis healthy.
- 2026-10-16 Day 1 complete: schema + migrate.sh, Express API (POST /repos, GET /jobs/:id, SSE), Python worker (Streams, safe clone, inventory), React progress UI. Verified end to end on octocat/Hello-World. 21 API tests + 22 worker tests pass.
