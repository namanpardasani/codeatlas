import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "./app.js";
import { config } from "./config.js";
import { pool } from "./db.js";

let dbUp = false;
let repoId = 0;
let stub: Server;
let received: { url?: string; body?: Record<string, unknown> } = {};
let stubStatus = 200;

beforeAll(async () => {
  stub = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      received = { url: req.url, body: raw ? JSON.parse(raw) : undefined };
      res.writeHead(stubStatus, { "Content-Type": "application/json" });
      res.end(JSON.stringify(stubStatus === 200 ? { hits: [{ path: "a.py", score: 0.03 }], terms: ["x"], mode: "hybrid" } : { error: "boom" }));
    });
  });
  await new Promise<void>((r) => stub.listen(0, "127.0.0.1", r));
  config.searchUrl = `http://127.0.0.1:${(stub.address() as AddressInfo).port}`;
  try {
    const r = await pool.query(`INSERT INTO repos (url, full_name) VALUES ('https://github.com/test/apisearch','test/apisearch')
                                ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id`);
    repoId = Number(r.rows[0].id);
    dbUp = true;
  } catch {
    dbUp = false;
  }
});

afterAll(async () => {
  stub.close();
  if (dbUp) await pool.query("DELETE FROM repos WHERE id = $1", [repoId]);
  await pool.end();
});

const post = (id: number | string, body: unknown) => request(createApp()).post(`/repos/${id}/search`).send(body as object);

describe("search API", () => {
  it("validates, applies defaults and forwards to the search service", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await post(repoId, { query: "  retry with backoff  " });
    expect(res.status).toBe(200);
    expect(res.body.hits[0].path).toBe("a.py");
    expect(received.url).toBe("/search");
    expect(received.body).toMatchObject({ repo_id: repoId, query: "retry with backoff", mode: "hybrid", chunking: "ast", limit: 10 });
  });

  it("passes the strategy switches and filters through", async ({ skip }) => {
    if (!dbUp) skip();
    await post(repoId, { query: "x", mode: "keyword", chunking: "fixed", limit: 5, language: "python", path_prefix: "src/" });
    expect(received.body).toMatchObject({ mode: "keyword", chunking: "fixed", limit: 5, language: "python", path_prefix: "src/" });
  });

  it("rejects bad input before it reaches the service", async ({ skip }) => {
    if (!dbUp) skip();
    received = {};
    for (const bad of [{}, { query: "" }, { query: "x".repeat(501) }, { query: "x", mode: "magic" }, { query: "x", limit: 500 },
                       { query: "x", chunking: "tiny" }, { query: 5 }]) {
      expect((await post(repoId, bad)).status, JSON.stringify(bad).slice(0, 40)).toBe(400);
    }
    expect((await post("abc", { query: "x" })).status).toBe(400);
    expect(received.url).toBeUndefined();
  });

  it("404s for an unknown repo", async ({ skip }) => {
    if (!dbUp) skip();
    expect((await post(999999999, { query: "x" })).status).toBe(404);
  });

  it("turns an upstream failure into 502; an unreachable service degrades to keyword search over the stored chunks", async ({ skip }) => {
    if (!dbUp) skip();
    stubStatus = 500;
    expect((await post(repoId, { query: "x" })).status).toBe(502);
    stubStatus = 200;
    const f = await pool.query("INSERT INTO files (repo_id, path, content_hash) VALUES ($1, 'src/retry.py', 'h') RETURNING id", [repoId]);
    await pool.query(
      `INSERT INTO chunks (repo_id, file_id, strategy, idx, path, language, kind, symbol, start_line, end_line, header, content, content_hash, embed_hash, tsv)
       VALUES ($1,$2,'ast',0,'src/retry.py','python','function','retry_with_backoff',1,9,'h','def retry_with_backoff(): sleep twice as long','c','e',
               to_tsvector('simple','def retry_with_backoff sleep twice as long'))`,
      [repoId, f.rows[0].id],
    );
    const good = config.searchUrl;
    config.searchUrl = "http://127.0.0.1:9";
    const res = await post(repoId, { query: "how does the retry backoff sleep? x'); DROP TABLE chunks; --" });
    config.searchUrl = good;
    expect(res.status).toBe(200);
    expect(res.body.mode).toBe("keyword");
    expect(res.body.warnings[0]).toMatch(/not available/);
    expect(res.body.hits[0]).toMatchObject({ path: "src/retry.py", symbol: "retry_with_backoff", start_line: 1 });
    expect((await pool.query("SELECT count(*)::int AS n FROM chunks WHERE repo_id = $1", [repoId])).rows[0].n).toBe(1);   // nothing was dropped
  });
});
