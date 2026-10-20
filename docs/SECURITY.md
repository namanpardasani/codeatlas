# Security review (Day 10)

Scope: the whole project (API, web, Python worker, search service, MCP server, database, deployment config). Method: read the
code paths that handle untrusted input (repo URLs, repo contents, queue messages, HTTP requests, tool arguments, LLM output),
grep for string-built SQL and logged secrets, run dependency audits, and test the fixes. Ranked by severity; **High items are
fixed**. Private repositories are out of scope for the demo and refused at the API.

## Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | **High** | Anyone could start unlimited analyses (clone + parse + embed): cost and denial of service | **Fixed**: GitHub login required in production (`AUTH_REQUIRED=1`), per-user cap per rolling 24 h (default 5), global queue cap (default 20, then 503 + Retry-After), GitHub pre-check refuses missing/private/oversized repos before queueing, `DEMO_MODE=1` disables analysis entirely |
| 2 | **High** | Per-IP rate limits would be useless or spoofable behind a reverse proxy (all users share the proxy IP, or `X-Forwarded-For` is trusted blindly) | **Fixed**: `TRUST_PROXY=<hops>` is explicit and off by default; production start-up refuses unsafe settings |
| 3 | **High** | Each progress stream (SSE) holds a Redis connection; unbounded streams exhaust connections | **Fixed**: cap per client (`SSE_MAX_PER_IP`, default 5) |
| 4 | **High** | Development defaults (salt `dev-only-salt`, `change-me` passwords, http URL) could reach production | **Fixed**: the API refuses to start with `NODE_ENV=production` unless they are replaced (`productionProblems`) |
| 5 | Medium | Clone URL regex used `.match` with `$`, which accepts a trailing newline | **Fixed**: `fullmatch`; also rejects names starting with `.`; the API allowlist was already strict |
| 6 | Medium | Directory walk had no cap on total entries (millions of tiny/ignored files inside the byte limit) | **Fixed**: `MAX_WALK_ENTRIES` (50,000) |
| 7 | Medium | A hostile `.gitignore` was compiled without limits (CPU) | **Fixed**: 64 KB, 2,000 lines, 300 chars per line |
| 8 | Medium | Prompt injection: repository text reaches the LLM (chat, generated docs) and agents (MCP) | **Mitigated, residual risk**: random per-request delimiters, "data not instructions" rule, no tools for the model, citation verifier discards hijacked answers, docs guard, MCP output sanitised/labelled and read-only. A determined text can still skew an answer; an agent that also holds powerful tools elsewhere can be steered |
| 9 | Medium | Search/chat service (Python) has no authentication | **Accepted by design**: it binds to loopback / the private Docker network and is only called by the API. Never publish its port |
| 10 | Medium | Job and repo ids are sequential; every read endpoint is public | **Accepted**: all analysed data is derived from public repositories. **If private repos are ever added, every endpoint needs per-user authorisation first** (the MCP server already has repo scoping) |
| 11 | Low | `git clone` follows redirects from github.com | Accepted: protocol allowlist is https only, hooks/symlinks/submodules disabled; renamed repos keep working |
| 12 | Low | No data retention or account deletion flow | Open (needed before a real launch) |
| 13 | Info | Dependency audit | `npm audit --omit=dev`: 0 vulnerabilities in api, web, mcp; `pip-audit`: none known (run 2026-10-21). CI repeats it |

## Checked and found sound

- **SSRF:** only `https://github.com/<owner>/<repo>` is accepted (API, then re-validated in the worker); GitHub's API is called at a fixed host; no user-controlled URL is fetched anywhere (MCP tools take none).
- **Malicious repositories:** `core.hooksPath=/dev/null` (hooks never run), `core.symlinks=false`, inventory skips symlinks and never follows them, `--no-recurse-submodules`, `protocol.allow=never` except https, shallow/blobless clone with time and size limits, binary and over-size files skipped, no archives are ever unpacked (so no zip bombs), parsing runs in a child process with a memory limit and timeout, nothing from the repo is executed.
- **Path traversal:** repository paths come from `os.walk` on the clone and are stored as data; no tool or endpoint turns a user string into a file-system path.
- **SQL injection:** every query is parameterised; the only interpolated fragments are fixed strings or whitelisted `ORDER BY` columns. MCP uses a read-only role (tested).
- **XSS:** React escapes; the Markdown renderer blanks every URL except internal ones and renders no images/HTML; exported Markdown HTML-escapes generated text.
- **CORS / CSRF:** one allowed origin; session cookie `HttpOnly; SameSite=Lax` (+`Secure` over https); state-changing requests carrying a session are refused when `Origin` differs; hardening headers on every response.
- **Secrets:** no GitHub token is ever stored (used once, then discarded); sessions and API keys are stored as SHA-256 hashes; logs print error messages only (no URLs with credentials, no tokens). OAuth uses `state` and PKCE (S256) with no scope (public profile).

## Operating notes

- Set `NODE_ENV=production`, `CLIENT_SALT`, strong DB/Redis passwords, `PUBLIC_URL` (https), `GITHUB_CLIENT_ID/SECRET`, `AUTH_REQUIRED=1`, `TRUST_PROXY` = your proxy hops.
- Keep Postgres, Redis and the search service off the public internet.
- The local-LLM and paid-provider guards from Day 6 still apply (`LLM_ALLOW_PAID=1` is required for paid providers).
