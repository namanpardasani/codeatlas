import { createHmac, generateKeyPairSync } from "node:crypto";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import request from "supertest";
import { createApp } from "./app.js";
import { config } from "./config.js";
import { pool } from "./db.js";
import { COMMENT_MARKER, appJwt, drainRuns, processRun, renderComment, verifySignature, type Deps } from "./githubApp.js";

let dbUp = false;
let repoId = 0;
const RESULT = {
  base_sha: "a".repeat(40), head_sha: "b".repeat(40),
  risk: { score: 64, label: "high", top_factors: ["large change (900 lines)", "touches a central file (lib/core.js)"],
          missing_cochanges: [{ text: "lib/router.js usually changes with lib/core.js (73% of its commits, 11 shared) but is not in this change" }] },
  impact: { files: [{ path: "lib/core.js", score: 1, distance: 0, reason: "seed" },
                    { path: "lib/app|x.js", score: 0.48, distance: 1, reason: "calls parse() which changed <b>" }] },
  tests: { summary: "3 of 120 tests selected (3%)", full_suite: false, full_suite_reasons: [], command: "npx mocha test/core.js" },
  reviewers: [{ name: "Ann", reason: "4 recent commit(s) to lib/core.js" }],
};
let serviceCalls: Array<Record<string, unknown>> = [];
const serviceFetch = (async (_url: unknown, init?: RequestInit) => {
  serviceCalls.push(JSON.parse(String(init?.body)));
  return new Response(JSON.stringify(RESULT), { status: 200, headers: { "Content-Type": "application/json" } });
}) as typeof fetch;

beforeAll(async () => {
  try {
    const r = await pool.query(`INSERT INTO repos (url, full_name, status) VALUES ('https://github.com/test/blastapi','test/blastapi','ready')
                                ON CONFLICT (url) DO UPDATE SET status = 'ready' RETURNING id`);
    repoId = Number(r.rows[0].id);
    dbUp = true;
  } catch {
    dbUp = false;
  }
});
afterAll(async () => {
  if (dbUp) {
    await pool.query("DELETE FROM github_pr_runs WHERE repo_full_name = 'test/blastapi'");
    await pool.query("DELETE FROM repos WHERE id = $1", [repoId]);
  }
});
beforeEach(async () => {
  serviceCalls = [];
  if (dbUp) await pool.query("DELETE FROM blast_results WHERE repo_id = $1", [repoId]);
});

describe("POST /repos/:id/blast-radius", () => {
  it.runIf(() => dbUp)("validates that exactly one well-formed input is given", async () => {
    const app = createApp({ blastFetch: serviceFetch });
    const bad = [{}, { commit_sha: "xyz" }, { pr_url: "https://evil.com/a/b/pull/1" }, { commit_sha: "abcdef1", diff: "x" },
                 { pr_url: "https://github.com/a/b/pull/0" }];
    for (const body of bad) expect((await request(app).post(`/repos/${repoId}/blast-radius`).send(body)).status).toBe(400);
    expect((await request(app).post(`/repos/999999999/blast-radius`).send({ commit_sha: "abcdef1" })).status).toBe(404);
    expect(serviceCalls).toHaveLength(0);
  });

  it.runIf(() => dbUp)("accepts a diff up to ~1 MB (above the global 10 kb JSON limit) and refuses bigger", async () => {
    const app = createApp({ blastFetch: serviceFetch });
    const ok = await request(app).post(`/repos/${repoId}/blast-radius`).send({ diff: "d".repeat(500_000) });
    expect(ok.status).toBe(200);
    expect(ok.body.risk.score).toBe(64);
    const big = await request(app).post(`/repos/${repoId}/blast-radius`).send({ diff: "d".repeat(1_200_000) });
    expect([400, 413]).toContain(big.status);
  });

  it.runIf(() => dbUp)("caches by input and serves the stored result by public id", async () => {
    const app = createApp({ blastFetch: serviceFetch });
    const first = await request(app).post(`/repos/${repoId}/blast-radius`).send({ commit_sha: "ABCDEF1" });
    expect(first.status).toBe(200);
    expect(first.body.cached).toBe(false);
    const again = await request(app).post(`/repos/${repoId}/blast-radius`).send({ commit_sha: "abcdef1" });
    expect(again.body.cached).toBe(true);
    expect(serviceCalls).toHaveLength(1);
    expect(serviceCalls[0]).toMatchObject({ repo_id: repoId, commit_sha: "ABCDEF1" });
    const one = await request(app).get(`/blast/${first.body.id}`);
    expect(one.status).toBe(200);
    expect(one.body.risk.label).toBe("high");
    const list = await request(app).get(`/repos/${repoId}/blast-radius`);
    expect(list.body[0]).toMatchObject({ kind: "commit", ref: "abcdef1", risk_score: 64 });
    expect((await request(app).get("/blast/../../etc")).status).toBe(404);
    expect((await request(app).get("/blast/short")).status).toBe(400);
  });

  it.runIf(() => dbUp)("read-only demo serves cached results only", async () => {
    const app = createApp({ blastFetch: serviceFetch });
    await request(app).post(`/repos/${repoId}/blast-radius`).send({ commit_sha: "1234567" });
    config.demoMode = true;
    try {
      expect((await request(app).post(`/repos/${repoId}/blast-radius`).send({ commit_sha: "1234567" })).status).toBe(200);
      expect((await request(app).post(`/repos/${repoId}/blast-radius`).send({ commit_sha: "7654321" })).status).toBe(403);
    } finally {
      config.demoMode = false;
    }
  });
});

describe("GitHub App", () => {
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const secret = "s".repeat(32);
  const sign = (body: string) => "sha256=" + createHmac("sha256", secret).update(body).digest("hex");
  const pr = (action: string, sha: string, priv = false) => JSON.stringify({
    action, installation: { id: 77 }, repository: { full_name: "test/blastapi", private: priv },
    pull_request: { number: 5, head: { sha } },
  });

  beforeAll(() => {
    config.githubApp.appId = "12345";
    config.githubApp.privateKey = privateKey.export({ type: "pkcs1", format: "pem" }).toString();
    config.githubApp.webhookSecret = secret;
  });

  it("verifies signatures in constant time and signs a valid RS256 app JWT", async () => {
    const body = Buffer.from('{"a":1}');
    expect(verifySignature(body, sign(body.toString()), secret)).toBe(true);
    expect(verifySignature(body, sign("{}"), secret)).toBe(false);
    expect(verifySignature(body, undefined, secret)).toBe(false);
    expect(verifySignature(body, "sha256=00", secret)).toBe(false);
    const jwt = appJwt("12345", config.githubApp.privateKey, 1_000_000);
    const [h, p, s] = jwt.split(".");
    const { createVerify } = await import("node:crypto");
    expect(createVerify("RSA-SHA256").update(`${h}.${p}`).verify(publicKey, Buffer.from(s, "base64url"))).toBe(true);
    expect(JSON.parse(Buffer.from(p, "base64url").toString())).toEqual({ iat: 999_940, exp: 1_000_540, iss: "12345" });
  });

  it("renders a comment with escaped repo text and a link", () => {
    const md = renderComment(RESULT, "https://app/x");
    expect(md.startsWith(COMMENT_MARKER)).toBe(true);
    expect(md).toContain("risk 64/100 (high)");
    expect(md).toContain("lib/app\\|x.js");                  // a | in a path cannot break the table
    expect(md).toContain("&lt;b&gt;");                       // repo-derived text is never raw HTML
    const mention = renderComment({ ...RESULT, reviewers: [{ name: "@octocat", reason: "x" }] }, "https://app/x");
    expect(mention).not.toMatch(/(^|[^\u200b])@octocat/);     // no @mention can fire from repo data
    expect(md).toContain("npx mocha test/core.js");
    expect(md).not.toContain("lib/core.js` | 1.00");          // the change itself is not listed as 'affected beyond'
  });

  it.runIf(() => dbUp)("webhook: auth, ping, dedupe, private repos, then one comment edited per push + neutral check", async () => {
    await pool.query("DELETE FROM github_pr_runs WHERE repo_full_name = 'test/blastapi'");
    const gh: Array<{ method: string; url: string; body?: Record<string, unknown> }> = [];
    let nextComment = 900;
    const ghFetch = (async (url: unknown, init?: RequestInit) => {
      const u = String(url);
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      gh.push({ method: init?.method ?? "GET", url: u.replace(config.githubApiUrl, ""), body });
      const json = (x: unknown, status = 200) => new Response(JSON.stringify(x), { status, headers: { "Content-Type": "application/json" } });
      if (u.includes("/access_tokens")) return json({ token: "ghs_secret_token", expires_at: new Date(Date.now() + 3600e3).toISOString() }, 201);
      if (u.endsWith("/comments?per_page=100")) return json([]);
      if (u.includes("/issues/5/comments")) return json({ id: nextComment++ }, 201);
      if (u.includes("/issues/comments/")) return json({ id: 900 });
      if (u.includes("/check-runs")) return json({ id: 4242 }, 201);
      return json({}, 404);
    }) as typeof fetch;
    const deps: Deps = { sleep: async () => {}, ensureAnalysed: async () => ({ repoId }),
                         runBlast: async () => ({ status: 200, body: RESULT }) };
    const app = createApp({ blastFetch: ghFetch, githubDeps: deps });
    const post = (body: string, delivery: string, event = "pull_request", sig = sign(body)) =>
      request(app).post("/github/webhook").set("content-type", "application/json").set("x-github-event", event)
        .set("x-github-delivery", delivery).set("x-hub-signature-256", sig).send(body);

    expect((await post(pr("opened", "c".repeat(40)), "d0", "pull_request", "sha256=bad")).status).toBe(401);
    expect((await post("{}", "dping", "ping")).status).toBe(200);
    expect((await post(pr("opened", "d".repeat(40), true), "dpriv")).body.ignored).toMatch(/private/);
    expect((await post(pr("closed", "d".repeat(40)), "dclosed")).body.ignored).toBe("event");

    const first = await post(pr("opened", "e".repeat(40)), `d1-${Date.now()}`);
    expect(first.status).toBe(202);
    expect(first.body.queued).toBe(true);
    await drainRuns();                                       // the webhook already queued the work
    const run1 = await pool.query("SELECT id FROM github_pr_runs WHERE repo_full_name = 'test/blastapi' AND head_sha = $1", ["e".repeat(40)]);
    await processRun(Number(run1.rows[0].id), ghFetch, deps);   // a second attempt is a no-op (already claimed)
    const dupe = await post(pr("opened", "e".repeat(40)), `d1b-${Date.now()}`);
    expect(dupe.body.ignored).toMatch(/already processed/);

    await post(pr("synchronize", "f".repeat(40)), `d2-${Date.now()}`);
    await drainRuns();

    const created = gh.filter((c) => c.method === "POST" && c.url === "/repos/test/blastapi/issues/5/comments");
    const edited = gh.filter((c) => c.method === "PATCH" && c.url === "/repos/test/blastapi/issues/comments/900");
    expect(created).toHaveLength(1);                         // first push: create
    expect(edited).toHaveLength(1);                          // second push: edit the same comment
    const checks = gh.filter((c) => c.url === "/repos/test/blastapi/check-runs");
    expect(checks).toHaveLength(2);
    expect(checks[0].body).toMatchObject({ conclusion: "neutral", status: "completed", head_sha: "e".repeat(40) });
    const runs = await pool.query("SELECT status, comment_id, check_run_id, blast_result_id FROM github_pr_runs WHERE repo_full_name = 'test/blastapi' ORDER BY id");
    expect(runs.rows.map((r) => r.status)).toEqual(["done", "done"]);
    expect(runs.rows[1]).toMatchObject({ comment_id: "900", check_run_id: "4242" });
    const stored = await pool.query("SELECT source FROM blast_results WHERE id = $1", [runs.rows[1].blast_result_id]);
    expect(stored.rows[0].source).toBe("github");
    const leaked = await pool.query("SELECT count(*)::int AS n FROM github_pr_runs WHERE error LIKE '%ghs_%'");
    expect(leaked.rows[0].n).toBe(0);                        // the token never lands in the database
  });
});
