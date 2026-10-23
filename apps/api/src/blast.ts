/**
 * Blast Radius routes. The analysis itself runs in the Python service (/blast), which owns the parsers and the git
 * clones; this layer validates input, enforces limits, caches results in Postgres and serves them.
 *
 *   POST /repos/:id/blast-radius   { pr_url | commit_sha | diff }  -> stored result (cached when the same input repeats)
 *   GET  /repos/:id/blast-radius   recent results for the repo
 *   GET  /blast/:publicId          one stored result (shareable link; the PR comment points here)
 *   POST /github/webhook           GitHub App deliveries (raw body: needed for the HMAC check)
 */
import express, { type Router } from "express";
import rateLimit from "express-rate-limit";
import { createHash, randomBytes } from "node:crypto";
import { z } from "zod";
import { pool } from "./db.js";
import { config } from "./config.js";
import { requireLogin } from "./auth.js";
import { acceptWebhook, enqueueRun, verifySignature, type Deps } from "./githubApp.js";

const MAX_DIFF = 1024 * 1024;
const blastSchema = z
  .object({
    pr_url: z.string().trim().max(300).regex(/^https:\/\/github\.com\/[A-Za-z0-9-]{1,39}\/[A-Za-z0-9._-]{1,100}\/pull\/[1-9][0-9]{0,8}\/?$/,
      "expected https://github.com/<owner>/<repo>/pull/<number>").optional(),
    commit_sha: z.string().trim().regex(/^[0-9a-fA-F]{7,40}$/, "expected a 7-40 character hex commit SHA").optional(),
    diff: z.string().max(MAX_DIFF).optional(),
  })
  .refine((b) => [b.pr_url, b.commit_sha, b.diff].filter(Boolean).length === 1, "give exactly one of pr_url, commit_sha, diff");

const publicId = () => randomBytes(12).toString("base64url");
const PR_CACHE_MINUTES = 10;           // a PR can get new commits; reuse a result briefly, then recompute

export function blastRouter(opts: { fetchImpl?: typeof fetch; deps?: Deps } = {}): Router {
  const r = express.Router();
  const doFetch = opts.fetchImpl ?? fetch;
  const limiter = rateLimit({ windowMs: 60 * 60_000, limit: config.blastPerUserPerHour, standardHeaders: true, legacyHeaders: false });

  r.post("/repos/:id/blast-radius", express.json({ limit: "1100kb" }), limiter, requireLogin, async (req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
      res.status(400).json({ error: "Invalid repo id" });
      return;
    }
    const body = blastSchema.safeParse(req.body ?? {});
    if (!body.success) {
      res.status(400).json({ error: body.error.issues.map((i) => i.message).join("; ") });
      return;
    }
    const repo = await pool.query("SELECT id, status FROM repos WHERE id = $1", [id]);
    if (repo.rowCount === 0) {
      res.status(404).json({ error: "Repo not found" });
      return;
    }
    const { pr_url, commit_sha, diff } = body.data;
    const kind = pr_url ? "pr" : commit_sha ? "commit" : "diff";
    const ref = pr_url ?? commit_sha?.toLowerCase() ?? `diff:${createHash("sha256").update(diff!).digest("hex").slice(0, 16)}`;
    const cached = await pool.query(
      `SELECT public_id, result FROM blast_results WHERE repo_id = $1 AND input_kind = $2 AND input_ref = $3
         AND ($2 <> 'pr' OR created_at > now() - make_interval(mins => $4::int)) ORDER BY id DESC LIMIT 1`,
      [id, kind, ref, PR_CACHE_MINUTES]);
    if (cached.rows[0]) {
      res.json({ id: cached.rows[0].public_id, cached: true, ...cached.rows[0].result });
      return;
    }
    if (config.demoMode) {
      res.status(403).json({ error: "This is a read-only demo: only pre-computed Blast Radius results are available." });
      return;
    }
    let upstream: Response;
    try {
      upstream = await doFetch(`${config.searchUrl}/blast`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_id: id, pr_url, commit_sha, diff }), signal: AbortSignal.timeout(300_000),
      });
    } catch {
      res.status(503).json({ error: "The analysis service is not running." });
      return;
    }
    const payload = (await upstream.json().catch(() => ({ error: "bad response" }))) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    if (upstream.status !== 200) {
      res.status(upstream.status >= 500 ? 502 : upstream.status).json({ error: payload.error ?? "analysis failed" });
      return;
    }
    const pid = publicId();
    await pool.query(
      `INSERT INTO blast_results (public_id, repo_id, input_kind, input_ref, base_sha, head_sha, risk_score, risk_label, source, result)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'api', $9)`,
      [pid, id, kind, ref, payload.base_sha ?? null, payload.head_sha ?? null, payload.risk?.score ?? null, payload.risk?.label ?? null, payload]);
    res.json({ id: pid, cached: false, ...payload });
  });

  r.get("/repos/:id/blast-radius", async (req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
      res.status(400).json({ error: "Invalid repo id" });
      return;
    }
    const rows = await pool.query(
      `SELECT public_id AS id, input_kind AS kind, input_ref AS ref, risk_score, risk_label, source, created_at,
              result->'pr'->>'title' AS title
       FROM blast_results WHERE repo_id = $1 ORDER BY id DESC LIMIT 20`, [id]);
    res.json(rows.rows);
  });

  r.get("/blast/:publicId", async (req, res) => {
    const pid = String(req.params.publicId);
    if (!/^[A-Za-z0-9_-]{8,40}$/.test(pid)) {
      res.status(400).json({ error: "Invalid id" });
      return;
    }
    const row = await pool.query("SELECT public_id, repo_id, source, created_at, result FROM blast_results WHERE public_id = $1", [pid]);
    if (!row.rows[0]) {
      res.status(404).json({ error: "Result not found" });
      return;
    }
    const x = row.rows[0];
    res.json({ id: x.public_id, repo_id: String(x.repo_id), source: x.source, created_at: x.created_at, ...x.result });
  });

  r.post("/github/webhook", express.raw({ type: "application/json", limit: "5mb" }), async (req, res) => {
    if (!config.githubApp.webhookSecret || !config.githubApp.appId) {
      res.status(503).json({ error: "GitHub App is not configured" });
      return;
    }
    const raw = Buffer.isBuffer(req.body) ? req.body : Buffer.alloc(0);
    if (!verifySignature(raw, req.get("x-hub-signature-256"), config.githubApp.webhookSecret)) {
      res.status(401).json({ error: "bad signature" });
      return;
    }
    let payload: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    try {
      payload = JSON.parse(raw.toString("utf8"));
    } catch {
      res.status(400).json({ error: "invalid JSON" });
      return;
    }
    const out = await acceptWebhook(String(req.get("x-github-event") ?? ""), String(req.get("x-github-delivery") ?? ""), payload);
    res.status(out.status).json(out.body);              // answer within GitHub's timeout; the work happens after
    if (out.runId) void enqueueRun(out.runId, doFetch, opts.deps);
  });

  return r;
}
