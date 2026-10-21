import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import request from "supertest";
import { createApp } from "./app.js";
import { pool } from "./db.js";
import { redis } from "./redis.js";

let dbUp = false;
let repoId = 0;
const xadd = vi.spyOn(redis, "xadd").mockImplementation((async () => "0-1") as never);   // never wake a real worker

beforeAll(async () => {
  try {
    const r = await pool.query(`INSERT INTO repos (url, full_name) VALUES ('https://github.com/test/reanalyze', 'test/reanalyze')
                                ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id`);
    repoId = Number(r.rows[0].id);
    dbUp = true;
  } catch {
    dbUp = false;
  }
});

beforeEach(async () => {
  xadd.mockClear();
  if (dbUp) await pool.query("DELETE FROM analysis_jobs WHERE repo_id = $1", [repoId]);
});

afterAll(async () => {
  if (dbUp) await pool.query("DELETE FROM repos WHERE id = $1", [repoId]);
  await pool.end();
});

const app = () => createApp();

describe("re-analysis API", () => {
  it("creates a job with the requested mode and wakes a worker exactly once", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await request(app()).post(`/repos/${repoId}/reanalyze`).send({ mode: "full" });
    expect(res.status).toBe(202);
    expect(res.body).toMatchObject({ repoId, alreadyRunning: false });
    const job = await pool.query("SELECT requested_mode, status FROM analysis_jobs WHERE id = $1", [res.body.jobId]);
    expect(job.rows[0]).toEqual({ requested_mode: "full", status: "queued" });
    expect(xadd).toHaveBeenCalledTimes(1);
    expect(xadd.mock.calls[0]).toContain(String(res.body.jobId));
  });

  it("defaults to auto (incremental when possible)", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await request(app()).post(`/repos/${repoId}/reanalyze`).send({});
    const job = await pool.query("SELECT requested_mode FROM analysis_jobs WHERE id = $1", [res.body.jobId]);
    expect(job.rows[0].requested_mode).toBe("auto");
  });

  it("returns the job that is already queued/running instead of failing or starting a second one", async ({ skip }) => {
    if (!dbUp) skip();
    const first = await request(app()).post(`/repos/${repoId}/reanalyze`).send({});
    const second = await request(app()).post(`/repos/${repoId}/reanalyze`).send({ mode: "full" });
    expect(second.status).toBe(202);
    expect(second.body).toMatchObject({ jobId: first.body.jobId, alreadyRunning: true });
    expect(xadd).toHaveBeenCalledTimes(1);                                              // nothing new enqueued
    expect((await pool.query("SELECT count(*)::int AS n FROM analysis_jobs WHERE repo_id = $1", [repoId])).rows[0].n).toBe(1);
  });

  it("starts a new job once the previous one has finished", async ({ skip }) => {
    if (!dbUp) skip();
    const first = await request(app()).post(`/repos/${repoId}/reanalyze`).send({});
    await pool.query("UPDATE analysis_jobs SET status = 'done' WHERE id = $1", [first.body.jobId]);
    const second = await request(app()).post(`/repos/${repoId}/reanalyze`).send({});
    expect(second.body.alreadyRunning).toBe(false);
    expect(second.body.jobId).not.toBe(first.body.jobId);
  });

  it("submitting an already-known repo URL twice reuses the active job too", async ({ skip }) => {
    if (!dbUp) skip();
    const a = await request(app()).post("/repos").send({ url: "https://github.com/test/reanalyze" });
    const b = await request(app()).post("/repos").send({ url: "https://github.com/test/reanalyze" });
    expect(a.status).toBe(202);
    expect(b.body).toMatchObject({ jobId: a.body.jobId, alreadyRunning: true });
  });

  it("validates input", async ({ skip }) => {
    if (!dbUp) skip();
    expect((await request(app()).post(`/repos/${repoId}/reanalyze`).send({ mode: "everything" })).status).toBe(400);
    expect((await request(app()).post("/repos/abc/reanalyze").send({})).status).toBe(400);
    expect((await request(app()).post("/repos/999999999/reanalyze").send({})).status).toBe(404);
  });

  it("exposes mode, change counts and timings on the job and in the analyses history", async ({ skip }) => {
    if (!dbUp) skip();
    await pool.query(
      `INSERT INTO analysis_jobs (repo_id, status, mode, requested_mode, files_total, files_added, files_modified, files_deleted,
                                  files_renamed, files_reused, duration_ms, stage_timings)
       VALUES ($1,'done','full','auto',100,100,0,0,0,0,18000,'{"parsing": 9000}'),
              ($1,'done','incremental','auto',100,1,2,0,1,96,4000,'{"parsing": 300}')`, [repoId]);
    const list = await request(app()).get(`/repos/${repoId}/analyses`);
    expect(list.status).toBe(200);
    expect(list.body.map((j: { mode: string }) => j.mode)).toEqual(["incremental", "full"]);       // newest first
    expect(list.body[0]).toMatchObject({ files_modified: 2, files_reused: 96, duration_ms: 4000, stage_timings: { parsing: 300 } });
    const one = await request(app()).get(`/jobs/${list.body[0].id}`);
    expect(one.body).toMatchObject({ mode: "incremental", files_renamed: 1, files_reused: 96, duration_ms: 4000 });
    expect((await request(app()).get("/repos/abc/analyses")).status).toBe(400);
  });
});

describe("analysed-repo list and the read-only demo front door", () => {
  it("lists ready public repos; the demo opens an analysed repo without queueing and refuses an unknown one", async ({ skip }) => {
    if (!dbUp) skip();
    const { config } = await import("./config.js");
    const ins = await pool.query(
      `INSERT INTO repos (url, full_name, status) VALUES ('https://github.com/demoopen/ready','demoopen/ready','ready')
       ON CONFLICT (url) DO UPDATE SET status = 'ready', is_public = true RETURNING id`);
    const rid = Number(ins.rows[0].id);
    await pool.query("DELETE FROM analysis_jobs WHERE repo_id = $1", [rid]);
    const job = await pool.query("INSERT INTO analysis_jobs (repo_id, status, commit_sha, finished_at) VALUES ($1,'done','abc1234',now()) RETURNING id", [rid]);
    try {
      const list = await request(app()).get("/repos");
      expect(list.status).toBe(200);
      const mine = list.body.find((r: { full_name: string }) => r.full_name === "demoopen/ready");
      expect(mine).toMatchObject({ id: String(rid), commit_sha: "abc1234" });
      expect(list.body.every((r: { full_name: string }) => !r.full_name.startsWith("test/"))).toBe(true);

      config.demoMode = true;
      xadd.mockClear();
      const open = await request(app()).post("/repos").send({ url: "https://github.com/demoopen/ready" });
      expect(open.status).toBe(200);
      expect(open.body).toMatchObject({ repoId: String(rid), jobId: String(job.rows[0].id), existing: true });
      expect(xadd).not.toHaveBeenCalled();                       // nothing queued
      const unknown = await request(app()).post("/repos").send({ url: "https://github.com/demoopen/never-analysed" });
      expect(unknown.status).toBe(403);                          // analysis stays disabled
      // a private repo is never opened through the demo door
      await pool.query("UPDATE repos SET is_public = false WHERE id = $1", [rid]);
      expect((await request(app()).post("/repos").send({ url: "https://github.com/demoopen/ready" })).status).toBe(403);
      expect((await request(app()).get("/repos")).body.some((r: { full_name: string }) => r.full_name === "demoopen/ready")).toBe(false);
    } finally {
      config.demoMode = false;
      await pool.query("DELETE FROM repos WHERE id = $1", [rid]);
    }
  });
});
