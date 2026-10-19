import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "./app.js";
import { config } from "./config.js";
import { pool } from "./db.js";

let dbUp = false;
let repoId = 0;
let otherRepoId = 0;
let stub: Server;
let upstreamBodies: Record<string, unknown>[] = [];
let script: Record<string, unknown>[] = [];
let upstreamStatus = 200;

const FINAL = {
  type: "final", status: "answered", answer: "`f` does X [C1].", model: "fake", usage: { input_tokens: 5, output_tokens: 3 },
  citations: [{ label: "C1", chunk_id: 1, path: "src/a.py", start_line: 3, end_line: 9 }], claims: [], issues: [], retrieved: [{ label: "C1" }],
};

beforeAll(async () => {
  stub = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      upstreamBodies.push(JSON.parse(raw));
      res.writeHead(upstreamStatus, { "Content-Type": "application/x-ndjson" });
      // write line by line, splitting one JSON line across two TCP writes to exercise buffering
      for (const ev of script) {
        const line = JSON.stringify(ev) + "\n";
        res.write(line.slice(0, 7));
        res.write(line.slice(7));
      }
      res.end();
    });
  });
  await new Promise<void>((r) => stub.listen(0, "127.0.0.1", r));
  config.searchUrl = `http://127.0.0.1:${(stub.address() as AddressInfo).port}`;
  try {
    for (const name of ["apichat", "apichat2"]) {
      const r = await pool.query(`INSERT INTO repos (url, full_name) VALUES ($1, $2) ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id`,
        [`https://github.com/test/${name}`, `test/${name}`]);
      if (name === "apichat") repoId = Number(r.rows[0].id); else otherRepoId = Number(r.rows[0].id);
    }
    const f = await pool.query(`INSERT INTO files (repo_id, path, language, content_hash) VALUES ($1,'src/a.py','python','h')
                                ON CONFLICT (repo_id, path) DO UPDATE SET language = 'python' RETURNING id`, [repoId]);
    await pool.query(`INSERT INTO file_contents (file_id, content) VALUES ($1, 'line1\nline2\nline3\n') ON CONFLICT (file_id) DO UPDATE SET content = EXCLUDED.content`, [f.rows[0].id]);
    dbUp = true;
  } catch {
    dbUp = false;
  }
});

afterAll(async () => {
  stub.close();
  if (dbUp) await pool.query("DELETE FROM repos WHERE id = ANY($1)", [[repoId, otherRepoId]]);
  await pool.end();
});

const chat = (id: number | string, body: unknown) => request(createApp()).post(`/repos/${id}/chat`).send(body as object);
const parseSse = (text: string) =>
  text.split("\n\n").filter(Boolean).map((block) => {
    const ev = /^event: (.*)$/m.exec(block)![1]!;
    return { ev, data: JSON.parse(/^data: (.*)$/m.exec(block)![1]!) };
  });

describe("chat API", () => {
  it("relays the answer as SSE, creates a session and stores both messages with verified citations", async ({ skip }) => {
    if (!dbUp) skip();
    script = [{ type: "status", stage: "retrieving" }, { type: "retrieval", query: "q", evidence: { strong: true } }, { type: "delta", text: "`f` does" }, FINAL];
    const res = await chat(repoId, { question: "what does f do?" });
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("text/event-stream");
    const events = parseSse(res.text);
    expect(events.map((e) => e.ev)).toEqual(["session", "status", "retrieval", "delta", "final"]);
    const sessionId = events[0]!.data.session_id as string;
    expect(sessionId).toMatch(/^[0-9a-f-]{36}$/);

    const hist = await request(createApp()).get(`/chat/sessions/${sessionId}`);
    expect(hist.body.messages.map((m: { role: string }) => m.role)).toEqual(["user", "assistant"]);
    expect(hist.body.messages[1]).toMatchObject({ status: "answered", content: "`f` does X [C1].", model: "fake" });
    expect(hist.body.messages[1].citations[0]).toMatchObject({ path: "src/a.py", start_line: 3, end_line: 9 });
  });

  it("sends earlier turns to the service for follow-ups and keeps the same session", async ({ skip }) => {
    if (!dbUp) skip();
    script = [FINAL];
    const first = parseSse((await chat(repoId, { question: "first question" })).text);
    const sid = first[0]!.data.session_id;
    upstreamBodies = [];
    await chat(repoId, { question: "and the second?", session_id: sid });
    expect(upstreamBodies[0]!.history).toEqual([{ q: "first question", a: "`f` does X [C1]." }]);
    expect(upstreamBodies[0]!.question).toBe("and the second?");
    expect(String(upstreamBodies[0]!.client_key)).toMatch(/^[0-9a-f]{24}$/);   // hashed, never the raw IP
  });

  it("stores errors as messages and forwards typed error events", async ({ skip }) => {
    if (!dbUp) skip();
    script = [{ type: "error", kind: "quota", message: "Daily limit reached", retry_after: 3600 }];
    const res = await chat(repoId, { question: "will hit the cap" });
    const events = parseSse(res.text);
    expect(events.at(-1)).toMatchObject({ ev: "error", data: { kind: "quota", retry_after: 3600 } });
    const hist = await request(createApp()).get(`/chat/sessions/${events[0]!.data.session_id}`);
    expect(hist.body.messages[1]).toMatchObject({ role: "assistant", status: "error", content: "Daily limit reached" });
  });

  it("reports an unavailable answer service instead of hanging", async ({ skip }) => {
    if (!dbUp) skip();
    const good = config.searchUrl;
    config.searchUrl = "http://127.0.0.1:9";
    const res = await chat(repoId, { question: "anyone there?" });
    config.searchUrl = good;
    expect(parseSse(res.text).at(-1)).toMatchObject({ ev: "error", data: { kind: "unavailable" } });
  });

  it("validates input and enforces session ownership by repo", async ({ skip }) => {
    if (!dbUp) skip();
    for (const bad of [{}, { question: "" }, { question: "x".repeat(1001) }, { question: "q", session_id: "not-a-uuid" }]) {
      expect((await chat(repoId, bad)).status).toBe(400);
    }
    expect((await chat("abc", { question: "q" })).status).toBe(400);
    expect((await chat(999999999, { question: "q" })).status).toBe(404);
    script = [FINAL];
    const sid = parseSse((await chat(repoId, { question: "mine" })).text)[0]!.data.session_id as string;
    expect((await chat(otherRepoId, { question: "q", session_id: sid })).status).toBe(404);          // wrong repo
    expect((await chat(repoId, { question: "q", session_id: "00000000-0000-4000-8000-000000000000" })).status).toBe(404);
    expect((await request(createApp()).get("/chat/sessions/1")).status).toBe(400);                    // sequential ids are not accepted
    expect((await request(createApp()).get("/chat/sessions/00000000-0000-4000-8000-000000000000")).status).toBe(404);
  });

  it("serves stored file text for the code viewer", async ({ skip }) => {
    if (!dbUp) skip();
    const ok = await request(createApp()).get(`/repos/${repoId}/file`).query({ path: "src/a.py" });
    expect(ok.status).toBe(200);
    expect(ok.body).toMatchObject({ path: "src/a.py", language: "python", content: "line1\nline2\nline3\n" });
    expect((await request(createApp()).get(`/repos/${repoId}/file`).query({ path: "nope.py" })).status).toBe(404);
    expect((await request(createApp()).get(`/repos/${repoId}/file`)).status).toBe(400);
  });
});
