// Local transport: the client (e.g. Claude Code) starts this process and talks to it over stdin/stdout.
// stdout is the protocol channel: NEVER print anything else to it (logs go to stderr).
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ANONYMOUS, authenticate } from "./auth.js";
import { config } from "./config.js";
import { createPool } from "./db.js";
import { CallLimiter } from "./limits.js";
import { buildServer } from "./server.js";

const db = createPool();
// Optional: CODEATLAS_API_KEY widens access from "public repos" to "public repos + the key owner's repos".
const key = process.env.CODEATLAS_API_KEY;
const principal = key ? await authenticate(db, key) : ANONYMOUS;
if (!principal) {
  console.error("[codeatlas-mcp] CODEATLAS_API_KEY is invalid, revoked or expired.");
  process.exit(1);
}
const server = buildServer(principal, { db, limiter: new CallLimiter(config.callsPerMinute, config.maxConcurrent) });
await server.connect(new StdioServerTransport());
console.error(`[codeatlas-mcp] stdio ready (${principal.label})`);
process.on("SIGINT", () => void db.end().finally(() => process.exit(0)));
