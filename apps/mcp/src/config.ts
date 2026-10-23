const env = process.env;

export const config = {
  // The MCP server connects with a read-only role (see `npm run admin -- setup-role`). A bug or a malicious tool
  // argument must not be able to write, whatever the code does.
  databaseUrl:
    env.MCP_DATABASE_URL ??
    `postgres://codeatlas_mcp:${env.MCP_DB_PASSWORD ?? "change-me-mcp"}@127.0.0.1:${env.POSTGRES_PORT ?? 5433}/${env.POSTGRES_DB ?? "codeatlas"}`,
  // admin CLI only (creates keys and the role)
  adminDatabaseUrl:
    env.DATABASE_URL ??
    `postgres://${env.POSTGRES_USER ?? "codeatlas"}:${env.POSTGRES_PASSWORD ?? "change-me-locally"}@127.0.0.1:${env.POSTGRES_PORT ?? 5433}/${env.POSTGRES_DB ?? "codeatlas"}`,
  searchUrl: env.SEARCH_URL ?? `http://127.0.0.1:${env.SEARCH_PORT ?? 8001}`,
  httpHost: env.MCP_HOST ?? "127.0.0.1",
  httpPort: Number(env.MCP_PORT ?? 4100),
  // calls per minute per key (per process for stdio)
  callsPerMinute: Number(env.MCP_CALLS_PER_MINUTE ?? 60),
  maxConcurrent: Number(env.MCP_MAX_CONCURRENT ?? 4),
  // hard cap on the text one tool call may return
  maxOutputChars: Number(env.MCP_MAX_OUTPUT_CHARS ?? 12_000),
  toolTimeoutMs: Number(env.MCP_TOOL_TIMEOUT_MS ?? 15_000),
  // Blast Radius parses the change and may clone the repo on first use: longer budget than other tools
  blastTimeoutMs: Number(env.MCP_BLAST_TIMEOUT_MS ?? 120_000),
  // extra Host header values accepted by the HTTP transport (DNS-rebinding protection), comma separated
  allowedHosts: (env.MCP_ALLOWED_HOSTS ?? "").split(",").map((s) => s.trim()).filter(Boolean),
};
