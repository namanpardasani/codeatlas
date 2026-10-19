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
};

export const eventsChannel = (jobId: number | string) => `job:${jobId}:events`;
