const env = process.env;

export const config = {
  port: Number(env.API_PORT ?? 4000),
  databaseUrl:
    env.DATABASE_URL ??
    `postgres://${env.POSTGRES_USER ?? "codeatlas"}:${env.POSTGRES_PASSWORD ?? "change-me-locally"}@127.0.0.1:${env.POSTGRES_PORT ?? 5433}/${env.POSTGRES_DB ?? "codeatlas"}`,
  redisUrl: env.REDIS_URL ?? `redis://127.0.0.1:${env.REDIS_PORT ?? 6380}`,
  jobStream: "analysis:jobs",
  // salt for hashing client IPs into the opaque key used for per-client LLM budgets (never stored raw)
  clientSalt: env.CLIENT_SALT ?? "dev-only-salt",
  // internal Python service that owns the embedding model (loopback only, never exposed publicly)
  searchUrl: env.SEARCH_URL ?? `http://127.0.0.1:${env.SEARCH_PORT ?? 8001}`,
  corsOrigin: env.WEB_ORIGIN ?? env.CORS_ORIGIN ?? "http://localhost:5173",

  // ---- Day 10: access control and limits ----
  // Public base URL of THIS API as the browser sees it (used for the OAuth callback and the Secure cookie flag).
  publicUrl: env.PUBLIC_URL ?? `http://localhost:${env.API_PORT ?? 4000}`,
  github: { clientId: env.GITHUB_CLIENT_ID ?? "", clientSecret: env.GITHUB_CLIENT_SECRET ?? "" },
  // true: submitting/re-analysing a repository needs a GitHub login. Off by default for local development.
  authRequired: env.AUTH_REQUIRED === "1",
  // true: read-only deployment; no analysis can be started (pre-analysed repos only).
  demoMode: env.DEMO_MODE === "1",
  sessionDays: Number(env.SESSION_DAYS ?? 7),
  // analyses (new repo or re-analysis) per user per rolling 24 h; anonymous callers only exist when login is optional
  analysesPerUserPerDay: Number(env.ANALYSES_PER_USER_PER_DAY ?? 5),
  analysesAnonPerDay: Number(env.ANALYSES_ANON_PER_DAY ?? (env.AUTH_REQUIRED === "1" ? 0 : 1000)),
  // jobs waiting for a worker; beyond this new submissions get 503 + Retry-After
  maxQueued: Number(env.MAX_QUEUED_JOBS ?? 20),
  // repositories larger than this (GitHub-reported, KB) are refused before any clone
  maxRepoKb: Number(env.MAX_REPO_KB ?? 150 * 1024),
  // number of reverse-proxy hops to trust for the client IP (0 = none). Wrong values let clients spoof X-Forwarded-For.
  trustProxy: Number(env.TRUST_PROXY ?? 0),
  sseMaxPerIp: Number(env.SSE_MAX_PER_IP ?? 5),
};

export const eventsChannel = (jobId: number | string) => `job:${jobId}:events`;
