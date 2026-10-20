// Remote transport: Streamable HTTP (stateless) behind a Bearer API key.
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express from "express";
import rateLimit from "express-rate-limit";
import { pathToFileURL } from "node:url";
import { authenticate, type Principal } from "./auth.js";
import { config } from "./config.js";
import { createPool, type Db } from "./db.js";
import { CallLimiter } from "./limits.js";
import { buildServer, type Deps } from "./server.js";

declare module "express-serve-static-core" {
  interface Request {
    principal?: Principal;
  }
}

export function createHttpApp(db: Db, extra: Partial<Deps> = {}) {
  const limiter = extra.limiter ?? new CallLimiter(config.callsPerMinute, config.maxConcurrent);
  const app = express();
  app.disable("x-powered-by");

  // DNS-rebinding protection: only accept requests addressed to a host we expect.
  const hosts = new Set([`127.0.0.1:${config.httpPort}`, `localhost:${config.httpPort}`, ...config.allowedHosts]);
  app.use((req, res, next) => {
    if (!hosts.has(String(req.headers.host))) return void res.status(403).json({ error: "Host not allowed" });
    next();
  });

  // Brute-force guard: bounded attempts per IP before the key is even looked at.
  app.use(rateLimit({ windowMs: 60_000, limit: 300, standardHeaders: true, legacyHeaders: false }));
  const failedAuth = rateLimit({ windowMs: 60_000, limit: 10, skipSuccessfulRequests: true, standardHeaders: true, legacyHeaders: false });

  app.get("/health", (_req, res) => void res.json({ ok: true }));

  app.use("/mcp", express.json({ limit: "64kb" }));
  app.use("/mcp", failedAuth, async (req, res, next) => {
    const m = /^Bearer (\S{1,200})$/.exec(String(req.headers.authorization ?? ""));
    try {
      const principal = await authenticate(db, m?.[1]);
      if (!principal) {
        res.setHeader("WWW-Authenticate", 'Bearer realm="codeatlas"');
        return void res.status(401).json({ error: "Missing or invalid API key" });
      }
      req.principal = principal;
      next();
    } catch (err) {
      console.error("[codeatlas-mcp] auth lookup failed:", err instanceof Error ? err.message : err);
      res.status(503).json({ error: "Authentication unavailable" });
    }
  });

  app.post("/mcp", async (req, res) => {
    // Stateless: a fresh server + transport per request, nothing kept between calls (nothing to hijack).
    const server = buildServer(req.principal!, { db, limiter, fetchImpl: extra.fetchImpl });
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    res.on("close", () => {
      void transport.close();
      void server.close();
    });
    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (err) {
      console.error("[codeatlas-mcp] request failed:", err instanceof Error ? err.message : err);
      if (!res.headersSent) res.status(500).json({ jsonrpc: "2.0", error: { code: -32603, message: "Internal error" }, id: null });
    }
  });
  // Stateless server: no server-initiated stream, no sessions to delete.
  const notAllowed = (_req: express.Request, res: express.Response) =>
    void res.status(405).set("Allow", "POST").json({ error: "Method not allowed" });
  app.get("/mcp", notAllowed);
  app.delete("/mcp", notAllowed);

  return app;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const db = createPool();
  createHttpApp(db).listen(config.httpPort, config.httpHost, () =>
    console.error(`[codeatlas-mcp] http listening on http://${config.httpHost}:${config.httpPort}/mcp`),
  );
}
