# Deployment

Free-tier facts below were looked up on 2026-10-21 (sources at the bottom). They change often and several third-party pages
disagree with the vendors' own pages, so re-check the vendor page before relying on a number.

## What a free host can and cannot do for this project

| Component | Needs | Free option | Verdict |
|---|---|---|---|
| Frontend | static files | served by the API process (single origin) | works |
| API (Node) | always-on-ish web process | Render free web service | works, sleeps after 15 min idle, ~30-60 s cold start, 750 h/month shared pool |
| Postgres + pgvector | HNSW, tsvector | Neon free: 0.5 GB per project, 100 CU-hours/month, scales to zero after 5 min, pgvector included | works. Our 4 demo repos are about 25 MB |
| Redis | job queue + progress pub/sub | Upstash free: 500,000 commands/month, 256 MB | works but only needed when analysis runs |
| Python worker | **long-running** clone/parse/embed jobs (minutes, RAM for the embedding model) | none verified | **does not fit a free web host** (free instances sleep and are not for production; no free background worker confirmed) |
| Search + chat service | embedding model in RAM (~0.5 GB with runtime), LLM | none verified for the model; chat also needs an LLM | semantic search/chat not live on free tiers; keyword search is |
| LLM | generation | local llama.cpp, or your own free-tier key (Groq, Gemini, OpenRouter) | not hosted; never enable paid providers without `LLM_ALLOW_PAID=1` |

Oracle Cloud's Always Free ARM VM is the only free option that could run everything (worker, search, even a small local LLM)
with Docker Compose. Reports in mid-2026 say the allowance was cut from 4 OCPU / 24 GB to 2 OCPU / 12 GB; Oracle's own
page still showed the old numbers when checked, so treat the VM size as unconfirmed. It needs a payment card on file, new
ARM capacity can be unavailable in a region, and over-provisioning can get instances disabled.

## Recommended setup (three tiers)

### Tier 1: live read-only demo (free, no card)

```
Browser ──► Render free web service  (image: Dockerfile, API + built web app, DEMO_MODE=1)
                   │
                   └──► Neon free Postgres + pgvector   (4 pre-analysed repos, ~25 MB)
```

No Redis, no worker, no search service. Steps:

1. Neon: create a project, copy the connection string (`?sslmode=require`).
2. Load the schema and the demo data from your machine:
   ```bash
   cd workers/analyzer
   export DATABASE_URL='postgres://...neon.tech/neondb?sslmode=require'
   uv run python -m analyzer.migrate
   # data exported earlier from your local DB (4.8 MB gzip):
   DATABASE_URL=<local url> uv run python ../../scripts/demo_data.py export ../../demo-data \
       sindresorhus/p-limit pallets/itsdangerous chalk/chalk psf/requests
   uv run python ../../scripts/demo_data.py import ../../demo-data
   ```
3. Render: New Web Service from this repo, Runtime Docker, Dockerfile path `Dockerfile`, free instance. Environment:
   `NODE_ENV=production`, `DEMO_MODE=1`, `DATABASE_URL`, `CLIENT_SALT` (random 32+ chars), `PUBLIC_URL=https://<service>.onrender.com/api`,
   `WEB_ORIGIN=https://<service>.onrender.com`. (`AUTH_REQUIRED` is not needed: nobody can analyse anything.)
4. Open the URL. The first request after 15 minutes idle takes up to a minute.

**What works live in Tier 1:** browsing the 4 repos (files, symbols, imports), the dependency graph and cycles, hotspots and
per-file metrics, the generated documentation viewer and Markdown export, keyword search over code chunks (the API falls
back to Postgres full-text search when no search service is configured), and the MCP server if run locally against the
same data.

**What does NOT work live in Tier 1:** analysing a new repo or re-analysing (disabled by design: no worker), hybrid/vector search
(needs the embedding model service), the chat with cited answers (needs the search service and an LLM), the evaluation harness.
GitHub login is pointless in demo mode and can stay unconfigured.

### Tier 2: the full pipeline locally (free, any machine with Docker)

```bash
cp .env.example .env            # set strong passwords
docker compose --profile app up --build
# http://localhost:4000 : analyse any public repo; chat needs LLM_PROVIDER (e.g. a local llama.cpp, free)
```

Services: Postgres+pgvector, Redis, one-shot migrations, worker, search/chat service (internal port only), and the app image
(API + web). Set `AUTH_REQUIRED=1` plus the GitHub OAuth variables to require login.

### Tier 3 (optional): everything live on an Oracle Always Free VM

Run Tier 2's compose file on the VM behind a TLS reverse proxy (Caddy), set `AUTH_REQUIRED=1`, `TRUST_PROXY=1`,
`NODE_ENV=production`, GitHub OAuth credentials, and limit analysis with `ANALYSES_PER_USER_PER_DAY` and `MAX_QUEUED_JOBS`.
Only worth it if you accept the card requirement and the capacity/size uncertainty above. A local 1.5B model is slow
(about a minute per answer on 4 cores); use a free-tier hosted LLM key instead if you want live chat.

### Fallback assets for the portfolio

The demo does not depend on any host being up: the full pipeline runs locally with Docker Compose, and a **recorded demo video**
(placeholder in the README; recording is yours to do) shows analysis, graph, hotspots, chat with citations, docs and MCP.

## Environment variables (production)

| Variable | Purpose |
|---|---|
| `NODE_ENV=production` | enables the start-up checks (the API refuses development defaults) |
| `DATABASE_URL`, `REDIS_URL` | storage (Redis not needed with `DEMO_MODE=1`) |
| `CLIENT_SALT` | salt for hashing client IPs (32+ random chars) |
| `PUBLIC_URL` | public base of the API **including `/api`** when served by the app image; must be https |
| `WEB_ORIGIN` | the site origin (CORS, CSRF check, post-login redirect) |
| `DEMO_MODE=1` | read-only: analysis disabled |
| `AUTH_REQUIRED=1`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | GitHub login to analyse (OAuth app callback: `<PUBLIC_URL>/auth/github/callback`) |
| `ANALYSES_PER_USER_PER_DAY` (5), `MAX_QUEUED_JOBS` (20), `MAX_REPO_KB` (153600) | cost limits |
| `TRUST_PROXY` | number of reverse-proxy hops (0 = none) |
| `SEARCH_URL` | internal URL of the Python service, if deployed |

## Blast Radius in each tier

- **Tier 1 (read-only demo):** saved Blast Radius results ship in `demo-data/` and are served from Postgres; the Blast
  Radius tab, share links and the Replay page work. New analyses are refused (no Python service on the free tier).
- **Tier 2 (local, full):** the Python service (`analyzer.service`) runs `/blast`; the API, the UI and the MCP tools
  call it. Optional: `GITHUB_TOKEN` (any free personal token, no scopes needed for public repos) raises the GitHub API
  limit for PR URLs from 60 to 5,000 requests per hour.
- **GitHub App (PR comments + check runs):** needs a public HTTPS URL for the webhook. Render's free tier sleeps and
  takes 30-60 s to wake, longer than GitHub waits for a webhook (10 s), so first deliveries after idle time fail; GitHub
  lets you redeliver them from the App's settings. A tunnel such as smee.io (free) works for a local demo.

### Creating the GitHub App (only you can do this)

1. GitHub > Settings > Developer settings > GitHub Apps > New GitHub App.
2. Webhook URL: `https://<your API host>/api/github/webhook` (local: a smee.io channel forwarding to
   `http://localhost:4000/github/webhook`). Webhook secret: a random string of 20+ characters.
3. Repository permissions: **Pull requests: Read and write** (comments), **Checks: Read and write**, **Contents: Read-only**,
   **Metadata: Read-only**. Subscribe to the **Pull request** event. Nothing else.
4. Create the App, note its **App ID**, and generate a **private key** (.pem).
5. Set on the API: `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` (the PEM; newlines may be written as `\n`),
   `GITHUB_WEBHOOK_SECRET`; optional `GITHUB_APP_RUNS_PER_HOUR` (default 30).
6. Install the App on a public repository. Opening a PR or pushing to one posts (or updates) one comment and a neutral
   check run. Repositories not analysed yet are analysed first (up to about 15 minutes) unless the deployment is a
   read-only demo.

| Variable | Purpose |
|---|---|
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` | GitHub App identity and webhook verification |
| `BLAST_PER_HOUR` (30) | Blast Radius analyses per client per hour |
| `BLAST_CLONE_DIR`, `BLAST_MAX_DIFF_BYTES`, `BLAST_RISK_MODEL` | service: clone cache, diff size limit, optional trained risk model |
| `GITHUB_TOKEN` | optional, service: higher GitHub API limit for PR URLs |

## Sources (looked up 2026-10-21)

- [GitHub: Authorizing OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps) (state, PKCE S256, token exchange, `GET /user`)
- [Neon pricing](https://neon.com/pricing) (free: 100 CU-hours, 0.5 GB per project, scale-to-zero after 5 minutes; pgvector included)
- [Render: deploy for free](https://docs.render.com/free) (750 instance-hours/month, spins down after 15 minutes, not for production)
- [Upstash Redis pricing](https://upstash.com/docs/redis/overall/pricing) (free: 500,000 commands/month, 256 MB)
- [InfoQ on Oracle's Always Free changes](https://infoq.com/news/2026/07/oracle-cloud-free-tier-limits/) versus [Oracle's Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) (conflicting)
