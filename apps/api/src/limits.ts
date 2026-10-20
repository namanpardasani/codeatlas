import { createHash } from "node:crypto";
import type { Request } from "express";
import { config } from "./config.js";
import { pool } from "./db.js";
import type { ParsedRepo } from "./github.js";

export interface Admission {
  userId: number | null;
  key: string | null;
}

export type Gate =
  | { ok: true; admission: Admission }
  | { ok: false; status: number; error: string; retryAfter?: number };

const clientKey = (ip: string | undefined) =>
  createHash("sha256").update(`${config.clientSalt}:${ip ?? "unknown"}`).digest("hex").slice(0, 24);

/**
 * Cost control for the expensive operation (clone + parse + embed): demo mode, per-user daily cap, global queue cap and,
 * for a repository we have not seen, a pre-check with GitHub (exists, public, not too large) before anything is queued.
 */
export async function admit(req: Request, o: { checkRepo?: ParsedRepo; fetchImpl?: typeof fetch } = {}): Promise<Gate> {
  if (config.demoMode)
    return { ok: false, status: 403, error: "This is a read-only demo: analysis is disabled. Explore the pre-analysed repositories, or run CodeAtlas locally to analyse your own." };

  const userId = req.user?.id ?? null;
  const key = userId === null ? clientKey(req.ip) : null;
  const cap = userId !== null ? config.analysesPerUserPerDay : config.analysesAnonPerDay;
  const used = await pool.query(
    `SELECT count(*)::int AS n, min(created_at) AS oldest FROM analysis_jobs
     WHERE created_at > now() - interval '24 hours' AND ${userId !== null ? "requested_by = $1" : "requested_by_key = $1"}`,
    [userId ?? key],
  );
  if (used.rows[0].n >= cap) {
    const retry = Math.max(60, Math.ceil((new Date(used.rows[0].oldest).getTime() + 86_400_000 - Date.now()) / 1000));
    return { ok: false, status: 429, error: `Daily analysis limit reached (${cap} per 24 hours). Try again later.`, retryAfter: retry };
  }

  const queued = await pool.query("SELECT count(*)::int AS n FROM analysis_jobs WHERE status = 'queued'");
  if (queued.rows[0].n >= config.maxQueued)
    return { ok: false, status: 503, error: "The analysis queue is full. Try again in a few minutes.", retryAfter: 120 };

  if (o.checkRepo) {
    const bad = await checkRepoOnGithub(o.checkRepo, o.fetchImpl);
    if (bad) return { ok: false, status: bad.status, error: bad.error };
  }
  return { ok: true, admission: { userId, key } };
}

/**
 * Best-effort pre-check against the fixed host api.github.com (no user-controlled host, so no SSRF). A 404 means
 * missing OR private: private repositories are out of scope. If GitHub cannot be reached we do not block: the worker
 * enforces the same size and file limits while cloning.
 */
export async function checkRepoOnGithub(repo: ParsedRepo, fetchImpl: typeof fetch = fetch): Promise<{ status: number; error: string } | null> {
  try {
    const res = await fetchImpl(`https://api.github.com/repos/${repo.owner}/${repo.name}`, {
      headers: { Accept: "application/vnd.github+json", "User-Agent": "codeatlas" },
      signal: AbortSignal.timeout(4000),
    });
    if (res.status === 404)
      return { status: 404, error: "Repository not found. It may be private: only public GitHub repositories are supported." };
    if (!res.ok) return null;                                   // rate limited or GitHub trouble: let the worker decide
    const info = (await res.json()) as { private?: boolean; size?: number; archived?: boolean };
    if (info.private === true) return { status: 400, error: "Private repositories are not supported." };
    if (typeof info.size === "number" && info.size > config.maxRepoKb)
      return { status: 413, error: `Repository is too large (${Math.round(info.size / 1024)} MB; limit ${Math.round(config.maxRepoKb / 1024)} MB).` };
    return null;
  } catch {
    return null;
  }
}
