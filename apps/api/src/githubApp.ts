/**
 * GitHub App for Blast Radius: on pull_request opened / synchronize / reopened, analyse the PR and post ONE comment
 * (edited on every push, never re-posted) plus a neutral check run (a heuristic must never block a merge).
 *
 * Security:
 *  - every webhook is authenticated with HMAC-SHA256 over the RAW body (X-Hub-Signature-256), compared in constant time;
 *  - deliveries are de-duplicated (X-GitHub-Delivery) and runs are idempotent per (repo, PR, head SHA);
 *  - only public repositories are processed; runs are rate limited per installation;
 *  - the App authenticates with a short-lived RS256 JWT, exchanged for an installation token kept in memory only;
 *    tokens are never logged or stored;
 *  - the only host contacted is api.github.com.
 * Docs used: "Validating webhook deliveries", "Generating a JWT for a GitHub App", "Authenticating as a GitHub App
 * installation", REST "Create a check run" and "Create/Update an issue comment".
 */
import { createHmac, createSign, randomBytes, timingSafeEqual } from "node:crypto";
import { pool } from "./db.js";
import { redis } from "./redis.js";
import { config } from "./config.js";

export const COMMENT_MARKER = "<!-- codeatlas-blast-radius -->";
const MAX_COMMENT = 60_000;            // GitHub's limit is 65,536 characters

export function verifySignature(raw: Buffer, header: string | undefined, secret: string): boolean {
  if (!secret || !header || !header.startsWith("sha256=")) return false;
  const expected = Buffer.from("sha256=" + createHmac("sha256", secret).update(raw).digest("hex"));
  const got = Buffer.from(header);
  return got.length === expected.length && timingSafeEqual(got, expected);
}

const b64url = (b: Buffer | string) => Buffer.from(b).toString("base64").replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");

/** App JWT: RS256, issued 60 s in the past (clock drift), valid 9 minutes (GitHub allows at most 10). */
export function appJwt(appId: string, pem: string, now = Math.floor(Date.now() / 1000)): string {
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = b64url(JSON.stringify({ iat: now - 60, exp: now + 540, iss: appId }));
  const sig = createSign("RSA-SHA256").update(`${header}.${payload}`).sign(pem);
  return `${header}.${payload}.${b64url(sig)}`;
}

type Fetch = typeof fetch;
const tokenCache = new Map<number, { token: string; expires: number }>();

async function gh(fetchImpl: Fetch, path: string, init: { method?: string; token: string; body?: unknown; app?: boolean }) {
  const res = await fetchImpl(`${config.githubApiUrl}${path}`, {
    method: init.method ?? "GET",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${init.token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "codeatlas-blast-radius",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
    body: init.body ? JSON.stringify(init.body) : undefined,
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) throw new Error(`GitHub ${init.method ?? "GET"} ${path.replace(/\d+/g, ":n")} -> ${res.status}`);
  return res.status === 204 ? null : res.json();
}

export async function installationToken(fetchImpl: Fetch, installationId: number): Promise<string> {
  const hit = tokenCache.get(installationId);
  if (hit && hit.expires - 60_000 > Date.now()) return hit.token;
  const jwt = appJwt(config.githubApp.appId, config.githubApp.privateKey);
  const d = (await gh(fetchImpl, `/app/installations/${installationId}/access_tokens`, { method: "POST", token: jwt })) as {
    token: string; expires_at: string;
  };
  tokenCache.set(installationId, { token: d.token, expires: Date.parse(d.expires_at) });
  return d.token;
}

// ---- comment ----------------------------------------------------------------------------------------------------

type Json = Record<string, any>;   // eslint-disable-line @typescript-eslint/no-explicit-any
// Repo-derived text is data: escape table pipes and HTML, and break @mentions (a zero-width space after @) so a file or
// author named "@someone" cannot make the bot notify people.
const esc = (s: unknown) =>
  String(s ?? "").replace(/[|<>`]/g, (c) => ({ "|": "\\|", "<": "&lt;", ">": "&gt;", "`": "'" })[c]!).replace(/@/g, "@\u200b");

/** Markdown for the PR comment. Repo-derived text (paths, names, reasons) is escaped: it is data, never markup. */
export function renderComment(result: Json, link: string): string {
  const r = result.risk ?? {};
  const icon = r.label === "high" ? "🔴" : r.label === "medium" ? "🟠" : "🟢";
  const lines: string[] = [COMMENT_MARKER, `## ${icon} CodeAtlas Blast Radius: risk ${r.score ?? "?"}/100 (${r.label ?? "unknown"})`, ""];
  if (r.top_factors?.length) lines.push("**Why:** " + r.top_factors.map(esc).join("; ") + ".", "");
  const files = (result.impact?.files ?? []).filter((f: Json) => f.distance > 0).slice(0, 10);
  if (files.length) {
    lines.push("### Most likely affected beyond this diff", "", "| File | Score | Because |", "|---|---|---|");
    for (const f of files) lines.push(`| \`${esc(f.path)}\` | ${Number(f.score).toFixed(2)} | ${esc(f.reason)} |`);
    lines.push("");
  }
  const missing = r.missing_cochanges ?? [];
  if (missing.length) {
    lines.push("### Possibly missing from this PR", "");
    for (const m of missing.slice(0, 5)) lines.push(`- ${esc(m.text)}`);
    lines.push("");
  }
  const t = result.tests;
  if (t) {
    lines.push("### Tests to run", "", t.full_suite ? `**Run the full suite:** ${esc(t.full_suite_reasons.join("; "))}` : esc(t.summary));
    if (t.command) lines.push("", "```sh", String(t.command).slice(0, 1500), "```");
    lines.push("");
  }
  if (result.reviewers?.length) {
    lines.push("### Suggested reviewers", "");
    for (const v of result.reviewers) lines.push(`- ${esc(v.name)}: ${esc(v.reason)}`);
    lines.push("");
  }
  lines.push(`[Open the interactive ripple view](${link}) · static analysis + git history only; this never blocks a merge.`);
  const body = lines.join("\n");
  return body.length > MAX_COMMENT ? body.slice(0, MAX_COMMENT - 40) + "\n\n…(truncated)" : body;
}

// ---- webhook handling -------------------------------------------------------------------------------------------

const HANDLED = new Set(["opened", "synchronize", "reopened", "ready_for_review"]);

export type WebhookOutcome = { status: number; body: Json };

export async function acceptWebhook(event: string, delivery: string, payload: Json): Promise<WebhookOutcome & { runId?: number }> {
  if (event === "ping") return { status: 200, body: { ok: true } };
  if (event !== "pull_request" || !HANDLED.has(payload.action)) return { status: 202, body: { ignored: "event" } };
  const repo = payload.repository;
  const pr = payload.pull_request;
  const installation = Number(payload.installation?.id);
  if (!repo || !pr || !installation) return { status: 400, body: { error: "malformed payload" } };
  if (repo.private) return { status: 202, body: { ignored: "private repositories are not supported" } };
  const fresh = await pool.query("INSERT INTO github_deliveries (delivery_id, event) VALUES ($1, $2) ON CONFLICT DO NOTHING RETURNING delivery_id",
    [String(delivery).slice(0, 100), event]);
  if (fresh.rowCount === 0) return { status: 202, body: { ignored: "duplicate delivery" } };
  const recent = await pool.query("SELECT count(*)::int AS n FROM github_pr_runs WHERE installation_id = $1 AND created_at > now() - interval '1 hour'",
    [installation]);
  if (recent.rows[0].n >= config.githubApp.runsPerInstallationPerHour) return { status: 202, body: { ignored: "rate limited" } };
  const run = await pool.query(
    `INSERT INTO github_pr_runs (installation_id, repo_full_name, pr_number, head_sha) VALUES ($1, $2, $3, $4)
     ON CONFLICT (repo_full_name, pr_number, head_sha) DO NOTHING RETURNING id`,
    [installation, String(repo.full_name).slice(0, 200), Number(pr.number), String(pr.head?.sha ?? "").slice(0, 40)]);
  if (run.rowCount === 0) return { status: 202, body: { ignored: "already processed this commit" } };
  return { status: 202, body: { queued: true }, runId: Number(run.rows[0].id) };
}

/** Background work: in-process queue, one run at a time (bounded load; the webhook already answered 202). */
let chain: Promise<void> = Promise.resolve();
/** Resolves when every run queued so far has finished (tests, graceful shutdown). */
export const drainRuns = () => chain;

export function enqueueRun(runId: number, fetchImpl: Fetch, deps: Deps = defaultDeps) {
  chain = chain.then(() => processRun(runId, fetchImpl, deps)).catch((e) => console.error("github run failed:", e instanceof Error ? e.message : e));
  return chain;
}

export interface Deps {
  runBlast: (repoId: number, prUrl: string) => Promise<{ status: number; body: Json }>;
  ensureAnalysed: (fullName: string) => Promise<{ repoId: number | null; reason?: string }>;
  sleep: (ms: number) => Promise<void>;
}

async function setRun(id: number, fields: Json) {
  const keys = Object.keys(fields);
  await pool.query(`UPDATE github_pr_runs SET ${keys.map((k, i) => `${k} = $${i + 2}`).join(", ")}, updated_at = now() WHERE id = $1`,
    [id, ...keys.map((k) => fields[k])]);
}

export async function processRun(runId: number, fetchImpl: Fetch, deps: Deps = defaultDeps): Promise<void> {
  // claim the run atomically: a retried delivery or a second process can never handle the same run twice
  const r = await pool.query("UPDATE github_pr_runs SET status = 'running', updated_at = now() WHERE id = $1 AND status = 'queued' RETURNING *",
    [runId]);
  const run = r.rows[0];
  if (!run) return;
  const [owner, name] = String(run.repo_full_name).split("/");
  const prUrl = `https://github.com/${owner}/${name}/pull/${run.pr_number}`;
  let token: string;
  try {
    token = await installationToken(fetchImpl, Number(run.installation_id));
  } catch (e) {
    await setRun(runId, { status: "failed", error: `installation token: ${e instanceof Error ? e.message : "error"}` });
    return;
  }
  try {
    const ready = await deps.ensureAnalysed(run.repo_full_name);
    if (!ready.repoId) {
      await upsertComment(fetchImpl, token, run, `${COMMENT_MARKER}\nCodeAtlas could not analyse this repository: ${esc(ready.reason)}`);
      await setRun(runId, { status: "failed", error: ready.reason ?? "not analysed" });
      return;
    }
    const out = await deps.runBlast(ready.repoId, prUrl);
    if (out.status !== 200) throw new Error(`analysis failed: ${String(out.body.error ?? out.status).slice(0, 200)}`);
    const publicId = b64url(randomBytes(12));
    const stored = await pool.query(
      `INSERT INTO blast_results (public_id, repo_id, input_kind, input_ref, base_sha, head_sha, risk_score, risk_label, source, result)
       VALUES ($1, $2, 'pr', $3, $4, $5, $6, $7, 'github', $8) RETURNING id`,
      [publicId, ready.repoId, prUrl, out.body.base_sha, out.body.head_sha, out.body.risk?.score ?? null, out.body.risk?.label ?? null, out.body]);
    const link = `${config.corsOrigin}/repo/${ready.repoId}/blast?result=${publicId}`;
    const commentId = await upsertComment(fetchImpl, token, run, renderComment(out.body, link));
    const check = (await gh(fetchImpl, `/repos/${owner}/${name}/check-runs`, {
      method: "POST", token,
      body: {
        name: "CodeAtlas Blast Radius", head_sha: run.head_sha, status: "completed", conclusion: "neutral",
        details_url: link,
        output: { title: `Risk ${out.body.risk?.score ?? "?"}/100 (${out.body.risk?.label ?? "unknown"})`,
                  summary: (out.body.risk?.top_factors ?? []).join("; ").slice(0, 1000) || "No risk factors." },
      },
    })) as { id: number };
    await setRun(runId, { status: "done", comment_id: commentId, check_run_id: check?.id ?? null, blast_result_id: stored.rows[0].id });
  } catch (e) {
    await setRun(runId, { status: "failed", error: (e instanceof Error ? e.message : String(e)).slice(0, 300) });
  }
}

/** Edit the PR's existing CodeAtlas comment (remembered, or found by its marker), otherwise create it. */
async function upsertComment(fetchImpl: Fetch, token: string, run: Json, body: string): Promise<number> {
  const [owner, name] = String(run.repo_full_name).split("/");
  const prev = await pool.query(
    "SELECT comment_id FROM github_pr_runs WHERE repo_full_name = $1 AND pr_number = $2 AND comment_id IS NOT NULL ORDER BY id DESC LIMIT 1",
    [run.repo_full_name, run.pr_number]);
  let id: number | null = prev.rows[0]?.comment_id ? Number(prev.rows[0].comment_id) : null;
  if (!id) {
    const list = (await gh(fetchImpl, `/repos/${owner}/${name}/issues/${run.pr_number}/comments?per_page=100`, { token })) as Json[];
    id = list?.find((c) => String(c.body ?? "").startsWith(COMMENT_MARKER))?.id ?? null;
  }
  if (id) {
    await gh(fetchImpl, `/repos/${owner}/${name}/issues/comments/${id}`, { method: "PATCH", token, body: { body } });
    return id;
  }
  const created = (await gh(fetchImpl, `/repos/${owner}/${name}/issues/${run.pr_number}/comments`, { method: "POST", token, body: { body } })) as { id: number };
  return created.id;
}

// ---- default dependencies (real service + analysis pipeline) ------------------------------------------------------

export const defaultDeps: Deps = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  runBlast: async (repoId, prUrl) => {
    const res = await fetch(`${config.searchUrl}/blast`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_id: repoId, pr_url: prUrl }), signal: AbortSignal.timeout(300_000),
    });
    return { status: res.status, body: (await res.json()) as Json };
  },
  ensureAnalysed: async (fullName) => {
    const url = `https://github.com/${fullName}`;
    const found = await pool.query("SELECT id, status FROM repos WHERE lower(url) = lower($1)", [url]);
    if (found.rows[0]?.status === "ready") return { repoId: Number(found.rows[0].id) };
    if (config.demoMode) return { repoId: null, reason: "this deployment is a read-only demo; the repository is not pre-analysed" };
    // start an analysis (same rows the normal submission creates), then wait for it, bounded
    const repo = found.rows[0] ?? (await pool.query(
      "INSERT INTO repos (url, full_name) VALUES ($1, $2) ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id", [url, fullName])).rows[0];
    const job = await pool.query(
      `INSERT INTO analysis_jobs (repo_id, status) VALUES ($1, 'queued')
       ON CONFLICT DO NOTHING RETURNING id`, [repo.id]);
    if (job.rows[0]) await redis.xadd(config.jobStream, "*", "jobId", String(job.rows[0].id));
    for (let i = 0; i < 60; i++) {                     // up to ~15 minutes
      await defaultDeps.sleep(15_000);
      const s = await pool.query("SELECT status FROM repos WHERE id = $1", [repo.id]);
      if (s.rows[0]?.status === "ready") return { repoId: Number(repo.id) };
      if (s.rows[0]?.status === "failed") return { repoId: null, reason: "the analysis of the repository failed" };
    }
    return { repoId: null, reason: "the analysis of the repository did not finish in time; push again to retry" };
  },
};
