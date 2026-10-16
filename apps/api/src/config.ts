const env = process.env;

export const config = {
  port: Number(env.API_PORT ?? 4000),
  databaseUrl:
    env.DATABASE_URL ??
    `postgres://${env.POSTGRES_USER ?? "codeatlas"}:${env.POSTGRES_PASSWORD ?? "change-me-locally"}@127.0.0.1:${env.POSTGRES_PORT ?? 5433}/${env.POSTGRES_DB ?? "codeatlas"}`,
  redisUrl: env.REDIS_URL ?? `redis://127.0.0.1:${env.REDIS_PORT ?? 6380}`,
  jobStream: "analysis:jobs",
  corsOrigin: env.WEB_ORIGIN ?? env.CORS_ORIGIN ?? "http://localhost:5173",
};

export const eventsChannel = (jobId: number | string) => `job:${jobId}:events`;
