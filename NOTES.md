# CodeAtlas Notes

## Architecture
- Monorepo: `apps/api` (Node/Express/TS), `apps/web` (React/Vite), `workers/analyzer` (Python 3.12), `db/migrations` (plain SQL).
- Infra via Docker Compose: Postgres 16 + pgvector (host port 5433), Redis 7 (host port 6380). Ports bind to 127.0.0.1 only.

## Decisions and tradeoffs
- Node API + Python worker; worker writes analysis results directly to Postgres, so schema is plain SQL migrations (not Prisma, which can't cleanly own pgvector/tsvector).
- Queue: Redis Streams (consumer group) instead of BullMQ, because BullMQ's Redis format is Node-specific. Job state lives in `analysis_jobs`; progress also via Redis pub/sub -> SSE.
- Python 3.12 via uv (3.14 is too new for some ML/tree-sitter wheels; to be verified on Day 2).
- Ports 5433/6380 chosen because FlagForge containers already use 5432/6379.

## What happens if X fails
- Docker storage goes read-only / image layer corrupt (`exec format error`): symptom of Docker Desktop disk write errors. Fix: restart Docker Desktop, `docker rmi` the bad image, re-pull. Avoid "Purge data" (wipes other projects' volumes).

## Interview Q&A

## Progress log
- 2026-10-16 Day 1, Step 1: monorepo folders, docker-compose.yml, .env.example. Postgres+pgvector (0.8.7) and Redis healthy.
