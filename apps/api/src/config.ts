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
  corsOrigin: env.WEB_ORIGIN ?? env.CORS_ORIGIN ?? env.RENDER_EXTERNAL_URL ?? "http://localhost:5173",

  // ---- Day 10: access control and limits ----
  // Public base URL of THIS API as the browser sees it (used for the OAuth callback and the Secure cookie flag).
  // Render sets RENDER_EXTERNAL_URL itself, so the free demo needs no manual URL settings
  publicUrl: env.PUBLIC_URL ?? (env.RENDER_EXTERNAL_URL ? `${env.RENDER_EXTERNAL_URL}/api` : `http://localhost:${env.API_PORT ?? 4000}`),
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

  // ---- Blast Radius ----
  blastPerUserPerHour: Number(env.BLAST_PER_HOUR ?? 30),
  // GitHub App (PR comments + check runs). Empty = the webhook answers 503 and nothing is posted.
  githubApp: {
    appId: env.GITHUB_APP_ID ?? "",
    privateKey: (env.GITHUB_APP_PRIVATE_KEY ?? "").replace(/\\n/g, "\n"),   // PEM; \n escapes allowed in env files
    webhookSecret: env.GITHUB_WEBHOOK_SECRET ?? "",
    runsPerInstallationPerHour: Number(env.GITHUB_APP_RUNS_PER_HOUR ?? 30),
  },
  githubApiUrl: "https://api.github.com",
};

export const eventsChannel = (jobId: number | string) => `job:${jobId}:events`;

/** Problems that make a production start unsafe. Development keeps its convenient defaults. */
export function productionProblems(c: typeof config = config, e: NodeJS.ProcessEnv = process.env): string[] {
  if (e.NODE_ENV !== "production") return [];
  const out: string[] = [];
  if (c.clientSalt === "dev-only-salt") out.push("CLIENT_SALT is the development default");
  if (/change-me/.test(c.databaseUrl)) out.push("DATABASE_URL still contains the placeholder password");
  if (c.authRequired && !(c.github.clientId && c.github.clientSecret)) out.push("AUTH_REQUIRED=1 but GITHUB_CLIENT_ID/SECRET are not set");
  if (!c.publicUrl.startsWith("https://")) out.push("PUBLIC_URL must be https:// (session cookies are Secure)");
  if (!c.demoMode && /change-me/.test(c.redisUrl)) out.push("REDIS_URL still contains the placeholder password");
  if (c.githubApp.appId && !(c.githubApp.privateKey.includes("PRIVATE KEY") && c.githubApp.webhookSecret.length >= 20))
    out.push("GITHUB_APP_ID is set but the private key or a webhook secret of 20+ characters is missing");
  return out;
}
