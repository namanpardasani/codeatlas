import express from "express";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { createApp } from "./app.js";
import { config, productionProblems } from "./config.js";

const problems = productionProblems();
if (problems.length) {
  console.error("Refusing to start in production:\n - " + problems.join("\n - "));
  process.exit(1);
}

const api = createApp();
const webDist = process.env.WEB_DIST;

if (webDist && existsSync(join(webDist, "index.html"))) {
  // Single-origin deployment: the API lives under /api (as in the Vite dev proxy) and the built web app is served by
  // the same process, so the session cookie is first-party (SameSite=Lax works) and no CORS is needed.
  const root = express();
  root.disable("x-powered-by");
  root.use("/api", api);
  root.use(express.static(webDist, { index: false, maxAge: "1h", setHeaders: (res, p) => {
    if (p.includes("/assets/")) res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
  } }));
  root.get(/^\/(?!api\/).*/, (_req, res) => {
    res.set("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data: https://avatars.githubusercontent.com; frame-ancestors 'none'");
    res.set("X-Content-Type-Options", "nosniff");
    res.sendFile(join(webDist, "index.html"));
  });
  root.listen(config.port, () => console.log(`api + web listening on :${config.port}`));
} else {
  api.listen(config.port, () => console.log(`api listening on :${config.port}`));
}
