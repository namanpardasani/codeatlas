import { afterAll, beforeAll, describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "./app.js";
import { pool } from "./db.js";

let dbUp = false;
let repoId = 0;
const ids: Record<string, number> = {};

beforeAll(async () => {
  try {
    await pool.query("SELECT 1");
    dbUp = true;
  } catch {
    return;
  }
  const r = await pool.query(
    `INSERT INTO repos (url, full_name) VALUES ('https://github.com/test/apigraph', 'test/apigraph')
     ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id`,
  );
  repoId = Number(r.rows[0].id);
  await pool.query("DELETE FROM files WHERE repo_id = $1", [repoId]);
  // a <-> b is a cycle; both import util; readme is not a graph node
  const rows: [string, string | null, number | null, number | null, number | null][] = [
    ["src/a.ts", "src", 0, 2, 0.2], ["src/b.ts", "src", 1, 2, 0.2], ["lib/util.ts", "lib", 2, 0, 0.6],
    ["README.md", null, null, null, null],
  ];
  for (const [path, mod, fin, fout, pr] of rows) {
    const f = await pool.query(
      `INSERT INTO files (repo_id, path, content_hash, module, fan_in, fan_out, pagerank, cycle_idx)
       VALUES ($1,$2,'h',$3,$4,$5,$6,$7) RETURNING id`,
      [repoId, path, mod, fin, fout, pr, path.startsWith("src/") ? 0 : null],
    );
    ids[path] = Number(f.rows[0].id);
  }
  const dep = (a: string, b: string) =>
    pool.query("INSERT INTO dependencies (repo_id, from_file_id, to_file_id, kinds) VALUES ($1,$2,$3,'[\"import\"]')",
      [repoId, ids[a], ids[b]]);
  await dep("src/a.ts", "src/b.ts"); await dep("src/b.ts", "src/a.ts");
  await dep("src/a.ts", "lib/util.ts"); await dep("src/b.ts", "lib/util.ts");
  await pool.query("INSERT INTO dependency_cycles (repo_id, cycle_idx, size, file_ids) VALUES ($1,0,2,$2)",
    [repoId, JSON.stringify([ids["src/a.ts"], ids["src/b.ts"]])]);
  await pool.query("INSERT INTO module_edges VALUES ($1,'src','lib',2), ($1,'src','src',2)", [repoId]);
});

afterAll(async () => {
  if (dbUp) await pool.query("DELETE FROM repos WHERE id = $1", [repoId]);
  await pool.end();
});

describe("graph API", () => {
  it("returns file nodes, edges and cycles; non-graph files are excluded", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await request(createApp()).get(`/repos/${repoId}/graph`);
    expect(res.status).toBe(200);
    expect(res.body.nodes.map((n: { path: string }) => n.path).sort()).toEqual(["lib/util.ts", "src/a.ts", "src/b.ts"]);
    expect(res.body.edges).toHaveLength(4);
    expect(res.body.cycles).toHaveLength(1);
    expect(res.body.truncated).toBe(false);
    expect(res.body.nodes[0].cycle_idx).toBe(0); // cycle members come first
  });

  it("caps the number of nodes and reports truncation; edges stay among returned nodes", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await request(createApp()).get(`/repos/${repoId}/graph?limit=2`);
    expect(res.body.nodes).toHaveLength(2);
    expect(res.body.truncated).toBe(true);
    expect(res.body.total_nodes).toBe(3);
    expect(res.body.edges).toHaveLength(2); // only a<->b
  });

  it("collapses to folders with aggregated edge counts", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await request(createApp()).get(`/repos/${repoId}/graph?mode=folders`);
    expect(res.body.nodes.map((n: { id: string }) => n.id).sort()).toEqual(["lib", "src"]);
    expect(res.body.edges).toEqual([{ source: "src", target: "lib", count: 2 }]);
    const src = res.body.nodes.find((n: { id: string }) => n.id === "src");
    expect(src).toMatchObject({ files: 2, files_in_cycles: 2, internal_edges: 2 });
  });

  it("lists dependencies, dependents and the cycle of a file", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await request(createApp()).get(`/files/${ids["src/a.ts"]}/graph`);
    expect(res.body.imports.map((f: { path: string }) => f.path)).toEqual(["lib/util.ts", "src/b.ts"]);
    expect(res.body.imported_by.map((f: { path: string }) => f.path)).toEqual(["src/b.ts"]);
    expect(res.body.cycle.map((f: { path: string }) => f.path)).toEqual(["src/a.ts", "src/b.ts"]);
  });

  it("rejects bad ids", async () => {
    expect((await request(createApp()).get("/repos/abc/graph")).status).toBe(400);
    expect((await request(createApp()).get("/files/0/graph")).status).toBe(400);
  });
});
