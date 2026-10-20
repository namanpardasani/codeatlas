import { afterAll, beforeAll, describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "./app.js";
import { pool } from "./db.js";
import { buildTree, footer, renderExport, renderFile, renderFolder, renderRepo, type DocsData } from "./docs.js";

const file = (path: string, extra: Partial<DocsData["files"][number]> = {}) => ({
  path, language: "python", lines: 50, fan_in: 2, fan_out: 1, pagerank: 0.1, hotspot_score: null, hotspot_reasons: null,
  max_complexity: 5, total_complexity: 12, churn: 3, cycle_idx: null, has_test: true, ...extra,
});

const DATA: DocsData = {
  repo: { full_name: "acme/demo", docs_status: "ready", docs_commit_sha: "abcdef1234567890", docs_model: "m-1", docs_generated_at: "2026-10-19T12:00:00Z" },
  facts: {
    languages: [{ language: "python", files: 3, lines: 1200 }],
    entry_points: [{ path: "main.py", why: "has an `if __name__` block" }],
    run_hints: [{ source: "README", title: "Install", commands: ["pip install demo"] }],
  },
  summaries: new Map([
    ["repo:", { summary: "A demo tool. It does things.", source: "llm" as const, model: "m-1" }],
    ["folder:pkg", { summary: "The `pkg/` package. More.", source: "extractive" as const, model: null }],
    ["file:pkg/core.py", { summary: "`pkg/core.py` computes totals.", source: "llm" as const, model: "m-1" }],
    ["symbol:pkg/core.py::total", { summary: "`total` sums prices.", source: "llm" as const, model: "m-1" }],
    ["file:main.py", { summary: "Runs <script>alert(1)</script> things.", source: "extractive" as const, model: null }],
  ]),
  files: [file("main.py"), file("pkg/core.py", { hotspot_score: 61.2, hotspot_reasons: [{ text: "complex and changes often", severity: "high" }], cycle_idx: 0 }),
          file("pkg/models.py", { has_test: false })],
  symbols: [{ path: "pkg/core.py", name: "total", kind: "function", parent_name: null, start_line: 5, end_line: 12, complexity: 8 }],
  imports: new Map([["pkg/core.py", ["pkg/models.py"]]]),
  importedBy: new Map([["pkg/core.py", ["main.py"]]]),
  cycles: [["pkg/core.py", "pkg/models.py"]],
};
const link = (t: string, p: string) => `doc:${t}:${encodeURIComponent(p)}`;

describe("docs renderers", () => {
  it("long first sentences are cut at a word boundary with an ellipsis, short ones are untouched", () => {
    const long = { ...DATA, summaries: new Map(DATA.summaries).set("file:pkg/core.py", { summary: "word ".repeat(80) + "end.", source: "llm" as const, model: "m" }) };
    const line = renderFolder(long, "pkg", null).split("\n").find((l) => l.includes("pkg/core.py"))!;
    expect(line.endsWith("…")).toBe(true);
    expect(line).not.toMatch(/wor…$/);
    expect(renderFolder(DATA, "pkg", null)).toContain("`pkg/core.py` computes totals.");
  });

  it("the repo page has the overview, facts, entry points, literal run hints, key modules, risks and the honesty footer", () => {
    const md = renderRepo(DATA, link);
    expect(md).toContain("# acme/demo");
    expect(md).toContain("A demo tool.");
    expect(md).toContain("**Languages:** python (3 files, 1,200 lines)");
    expect(md).toContain("## Entry points");
    expect(md).toContain("`main.py` — has an `if __name__` block");
    expect(md).toMatch(/## How to run[\s\S]*pip install demo/);
    expect(md).toContain("## Key modules");
    expect(md).toContain("1 circular dependency group(s)");
    expect(md).toMatch(/### Hotspots[\s\S]*pkg\/core\.py[\s\S]*61\.2/);
    expect(md).toContain("[`pkg/`](doc:folder:pkg)");
  });

  it("every page ends with the 'generated from commit X on date' footer", () => {
    for (const md of [renderRepo(DATA, link), renderFolder(DATA, "pkg", link), renderFile(DATA, "pkg/core.py", link)]) {
      expect(md).toContain("generated from commit `abcdef1` on 2026-10-19 (model `m-1`)");
      expect(md).toContain("screened automatically");
      expect(md).toContain("cannot catch every inaccuracy");
    }
    expect(footer({ ...DATA.repo, docs_commit_sha: null, docs_generated_at: null, docs_model: null })).toContain("unknown commit");
  });

  it("extractive summaries are labelled as such; LLM summaries are not", () => {
    expect(renderFolder(DATA, "pkg", link)).toContain("(extractive: assembled without an LLM)");
    expect(renderFile(DATA, "pkg/core.py", link)).not.toContain("(extractive");
  });

  it("file pages list symbols with their summaries, dependencies, dependents and metrics", () => {
    const md = renderFile(DATA, "pkg/core.py", link);
    expect(md).toContain("`total` (function, lines 5–12, complexity 8) — `total` sums prices.");
    expect(md).toContain("## Imports (files in this repo)");
    expect(md).toContain("[`pkg/models.py`](doc:file:pkg%2Fmodels.py)");
    expect(md).toContain("## Used by");
    expect(md).toContain("max complexity 5 (total 12)");
    expect(md).toContain("part of a circular dependency group");
    expect(md).toContain("**Hotspot score 61.2.** complex and changes often");
  });

  it("generated text can never inject HTML into the Markdown", () => {
    expect(renderFile(DATA, "main.py", link)).toContain("Runs &lt;script>alert(1)&lt;/script> things.");
    expect(renderFile(DATA, "main.py", link)).not.toContain("<script>");
  });

  it("the export is plain Markdown (no app links) containing every page", () => {
    const md = renderExport(DATA);
    expect(md).not.toContain("](doc:");
    for (const heading of ["# acme/demo", "# `pkg/`", "# `main.py`", "# `pkg/core.py`", "# `pkg/models.py`"]) expect(md).toContain(heading);
    expect(md.match(/generated from commit/g)!.length).toBe(1 + 1 + 3);        // repo + folder + 3 files
  });

  it("the tree nests folders before files with short summaries", () => {
    const tree = buildTree(DATA);
    expect(tree.map((n) => `${n.type}:${n.path}`)).toEqual(["folder:pkg", "file:main.py"]);
    expect(tree[0]!.children!.map((n) => n.path)).toEqual(["pkg/core.py", "pkg/models.py"]);
    expect(tree[0]!.summary).toBe("The `pkg/` package.");
    expect(tree[0]!.children![0]!.source).toBe("llm");
  });
});

let dbUp = false;
let repoId = 0;
beforeAll(async () => {
  try {
    const r = await pool.query(`INSERT INTO repos (url, full_name, docs_status, docs_commit_sha, docs_model, docs_generated_at)
      VALUES ('https://github.com/test/apidocs', 'test/apidocs', 'ready', 'abc1234def', 'm-1', now())
      ON CONFLICT (url) DO UPDATE SET docs_status = 'ready', docs_commit_sha = 'abc1234def', docs_model = 'm-1', docs_generated_at = now() RETURNING id`);
    repoId = Number(r.rows[0].id);
    await pool.query("DELETE FROM files WHERE repo_id = $1", [repoId]);
    await pool.query("DELETE FROM doc_summaries WHERE repo_id = $1", [repoId]);
    for (const p of ["app/main.py", "app/util.py", "setup.py"]) {
      await pool.query(`INSERT INTO files (repo_id, path, language, content_hash, module, lines, pagerank, fan_in) VALUES ($1,$2,'python','h','m',40,0.3,1)`, [repoId, p]);
    }
    await pool.query(`INSERT INTO doc_summaries (repo_id, target_type, target_ref, input_hash, summary, source) VALUES
      ($1,'repo','','h','Repo summary.','llm'), ($1,'folder','app','h','The \`app/\` folder.','extractive'),
      ($1,'file','app/main.py','h','\`app/main.py\` starts it.','llm'), ($1,'file','app/util.py','h','\`app/util.py\` helps.','extractive'),
      ($1,'file','setup.py','h','\`setup.py\` installs.','extractive')`, [repoId]);
    await pool.query("INSERT INTO repo_facts (repo_id, facts) VALUES ($1, $2) ON CONFLICT (repo_id) DO UPDATE SET facts = EXCLUDED.facts",
      [repoId, JSON.stringify({ entry_points: [{ path: "app/main.py", why: "conventional entry file name" }] })]);
    dbUp = true;
  } catch {
    dbUp = false;
  }
});
afterAll(async () => {
  if (dbUp) await pool.query("DELETE FROM repos WHERE id = $1", [repoId]);
  await pool.end();
});

describe("docs API", () => {
  const get = (path: string) => request(createApp()).get(path);

  it("status, tree and pages", async ({ skip }) => {
    if (!dbUp) skip();
    const st = await get(`/repos/${repoId}/docs/status`);
    expect(st.body).toMatchObject({ docs_status: "ready", targets: 5, llm: 2, extractive: 3 });
    const tree = await get(`/repos/${repoId}/docs/tree`);
    expect(tree.body.summary).toBe("Repo summary.");
    expect(tree.body.tree.map((n: { path: string }) => n.path)).toEqual(["app", "setup.py"]);
    const page = await get(`/repos/${repoId}/docs/page?type=file&path=app/main.py`);
    expect(page.status).toBe(200);
    expect(page.body.markdown).toContain("`app/main.py` starts it.");
    expect(page.body).toMatchObject({ source: "llm", commit: "abc1234def" });
    expect((await get(`/repos/${repoId}/docs/page?type=repo&path=`)).body.markdown).toContain("# test/apidocs");
    expect((await get(`/repos/${repoId}/docs/page?type=folder&path=app`)).body.markdown).toContain("`app/main.py`");
  });

  it("rejects bad requests and unknown paths", async ({ skip }) => {
    if (!dbUp) skip();
    expect((await get(`/repos/${repoId}/docs/page?type=file&path=nope.py`)).status).toBe(404);
    expect((await get(`/repos/${repoId}/docs/page?type=folder&path=ghost`)).status).toBe(404);
    expect((await get(`/repos/${repoId}/docs/page?type=weird&path=x`)).status).toBe(400);
    expect((await get("/repos/abc/docs/tree")).status).toBe(400);
    expect((await get("/repos/999999999/docs/tree")).status).toBe(404);
  });

  it("exports one Markdown file as an attachment", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await get(`/repos/${repoId}/docs/export.md`);
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("text/markdown");
    expect(res.headers["content-disposition"]).toBe('attachment; filename="test-apidocs-docs.md"');
    expect(res.text).toContain("# test/apidocs");
    expect(res.text).toContain("# `app/util.py`");
    expect(res.text).not.toContain("](doc:");
  });

  it("says so when the docs have not been generated", async ({ skip }) => {
    if (!dbUp) skip();
    await pool.query("DELETE FROM doc_summaries WHERE repo_id = $1", [repoId]);
    expect((await get(`/repos/${repoId}/docs/page?type=repo&path=`)).status).toBe(404);
    expect((await get(`/repos/${repoId}/docs/export.md`)).status).toBe(404);
  });
});
