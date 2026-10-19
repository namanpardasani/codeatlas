import { afterAll, beforeAll, describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "./app.js";
import { pool } from "./db.js";

let dbUp = false;
let repoId = 0;
const ids: Record<string, number> = {};

const q = (sql: string, params: unknown[] = []) => pool.query(sql, params);

beforeAll(async () => {
  try {
    await q("SELECT 1");
    dbUp = true;
  } catch {
    return;
  }
  const r = await q(`INSERT INTO repos (url, full_name) VALUES ('https://github.com/test/apihot', 'test/apihot')
                     ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id`);
  repoId = Number(r.rows[0].id);
  await q("DELETE FROM files WHERE repo_id = $1", [repoId]);
  await q("DELETE FROM analysis_jobs WHERE repo_id = $1", [repoId]);
  await q(`INSERT INTO analysis_jobs (repo_id, status, history_commits, history_window_days, history_truncated)
           VALUES ($1, 'done', 120, 90, true)`, [repoId]);
  // path, max_complexity, churn, score(null = formula not implemented), is_test, in graph
  const rows: [string, number, number, number | null, boolean, boolean][] = [
    ["src/hot.ts", 30, 20, 88.5, false, true],
    ["src/calm.ts", 12, 1, 20.25, false, true],
    ["src/trivial.ts", 2, 30, 5, false, true],
    ["src/hot.test.ts", 5, 9, null, true, true],
    ["README.md", 0, 0, null, false, false],
  ];
  for (const [path, cc, churn, score, isTest, inGraph] of rows) {
    const f = await q(
      `INSERT INTO files (repo_id, path, content_hash, is_test, module, lines, code_lines, max_complexity, total_complexity,
                          churn, authors, hotspot_score, hotspot_reasons, has_test, dup_ratio, fan_in)
       VALUES ($1,$2,'h',$3,$4,100,80,$5,$5,$6,3,$7,$8,false,0.1,2) RETURNING id`,
      [repoId, path, isTest, inGraph ? "src" : null, cc, churn, score,
       JSON.stringify(score ? [{ factor: "complexity", points: 20, severity: "high", text: "complex" }] : [])],
    );
    ids[path] = Number(f.rows[0].id);
  }
  await q(`INSERT INTO symbols (repo_id, file_id, idx, name, kind, start_line, end_line, complexity, max_nesting, param_count)
           VALUES ($1,$2,0,'big','function',1,40,30,4,3), ($1,$2,1,'small','function',50,52,2,0,1), ($1,$2,2,'K','class',60,90,NULL,0,0)`,
    [repoId, ids["src/hot.ts"]]);
  await q(`INSERT INTO file_cochange VALUES ($1,$2,$3,6,0.75)`, [repoId, ids["src/hot.ts"], ids["src/calm.ts"]]);
  await q(`INSERT INTO duplicate_groups VALUES ($1,0,12,80,2)`, [repoId]);
  await q(`INSERT INTO duplicate_blocks VALUES ($1,0,$2,10,21), ($1,0,$3,30,41)`, [repoId, ids["src/hot.ts"], ids["src/calm.ts"]]);
});

afterAll(async () => {
  if (dbUp) await q("DELETE FROM repos WHERE id = $1", [repoId]);
  await pool.end();
});

const get = (path: string) => request(createApp()).get(path);
const paths = (body: { items: { path: string }[] }) => body.items.map((i) => i.path);

describe("hotspots API", () => {
  it("ranks by score by default and excludes test files and non-source files", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await get(`/repos/${repoId}/hotspots`);
    expect(res.status).toBe(200);
    expect(res.body.scored).toBe(true);
    expect(paths(res.body)).toEqual(["src/hot.ts", "src/calm.ts", "src/trivial.ts"]);
    expect(res.body.items[0].hotspot_reasons[0].factor).toBe("complexity");
    expect(res.body.history).toEqual({ available: true, commits: 120, window_days: 90, truncated: true });
  });

  it("sorts by any whitelisted column, both directions; unknown sort falls back to score", async ({ skip }) => {
    if (!dbUp) skip();
    expect(paths((await get(`/repos/${repoId}/hotspots?sort=churn`)).body)).toEqual(["src/trivial.ts", "src/hot.ts", "src/calm.ts"]);
    expect(paths((await get(`/repos/${repoId}/hotspots?sort=complexity&dir=asc`)).body)).toEqual(["src/trivial.ts", "src/calm.ts", "src/hot.ts"]);
    expect(paths((await get(`/repos/${repoId}/hotspots?sort=path;DROP TABLE files`)).body)[0]).toBe("src/hot.ts");
    expect((await get(`/repos/${repoId}/hotspots?limit=1`)).body.items).toHaveLength(1);
  });

  it("falls back to complexity ordering when no formula has produced scores", async ({ skip }) => {
    if (!dbUp) skip();
    await q("UPDATE files SET hotspot_score = NULL WHERE repo_id = $1", [repoId]);
    const res = await get(`/repos/${repoId}/hotspots`);
    expect(res.body.scored).toBe(false);
    expect(res.body.sort).toBe("complexity");
    expect(paths(res.body)).toEqual(["src/hot.ts", "src/calm.ts", "src/trivial.ts"]);
  });

  it("returns co-change pairs", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await get(`/repos/${repoId}/cochange`);
    expect(res.body).toEqual([{ file_a: "src/hot.ts", file_b: "src/calm.ts", count: 6, coupling: 0.75 }]);
  });

  it("returns per-file metrics: functions by complexity, duplicates with other locations, co-change partners", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await get(`/files/${ids["src/hot.ts"]}/metrics`);
    expect(res.status).toBe(200);
    expect(res.body.file.max_complexity).toBe(30);
    expect(res.body.functions.map((f: { name: string }) => f.name)).toEqual(["big", "small"]); // class has no complexity
    expect(res.body.functions[0]).toMatchObject({ complexity: 30, max_nesting: 4, param_count: 3, length: 40 });
    expect(res.body.duplicates).toHaveLength(1);
    expect(res.body.duplicates[0].others).toEqual([{ path: "src/calm.ts", start_line: 30, end_line: 41 }]);
    expect(res.body.cochange).toEqual([{ path: "src/calm.ts", count: 6, coupling: 0.75 }]);
  });

  it("validates ids", async () => {
    expect((await get("/repos/x/hotspots")).status).toBe(400);
    expect((await get("/files/0/metrics")).status).toBe(400);
    expect((await get("/repos/x/cochange")).status).toBe(400);
  });
});
