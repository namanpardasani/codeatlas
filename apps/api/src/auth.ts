import { createHash, randomBytes } from "node:crypto";
import type { NextFunction, Request, RequestHandler, Response, Router } from "express";
import { Router as makeRouter } from "express";
import { config } from "./config.js";
import { pool } from "./db.js";

// GitHub OAuth web flow (docs.github.com "Authorizing OAuth apps", verified 2026-10): authorize with state + PKCE (S256),
// exchange the code with the client secret, read GET /user, then DISCARD the token. We store no GitHub token at all, so
// there is nothing to encrypt or leak; the session cookie is an opaque random value whose SHA-256 is stored.
const AUTHORIZE = "https://github.com/login/oauth/authorize";
const TOKEN = "https://github.com/login/oauth/access_token";
const USER_API = "https://api.github.com/user";

export const COOKIE = "ca_session";
const OAUTH_COOKIE = "ca_oauth";
const sha256 = (s: string) => createHash("sha256").update(s).digest("hex");
const b64url = (b: Buffer) => b.toString("base64url");
const secureCookies = () => config.publicUrl.startsWith("https://");

export interface SessionUser {
  id: number;
  login: string;
  avatarUrl: string | null;
}

declare module "express-serve-static-core" {
  interface Request {
    user?: SessionUser;
  }
}

export function parseCookies(header: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of (header ?? "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}

function setCookie(res: Response, name: string, value: string, maxAgeS: number) {
  const attrs = [`${name}=${encodeURIComponent(value)}`, "Path=/", "HttpOnly", "SameSite=Lax", `Max-Age=${maxAgeS}`];
  if (secureCookies()) attrs.push("Secure");
  res.append("Set-Cookie", attrs.join("; "));
}

const clearCookie = (res: Response, name: string) => setCookie(res, name, "", 0);

/** Attaches req.user when a valid, unexpired session cookie is present. Never throws. */
export const loadUser: RequestHandler = async (req, _res, next) => {
  try {
    const token = parseCookies(req.headers.cookie)[COOKIE];
    if (token && /^[A-Za-z0-9_-]{43}$/.test(token)) {
      const r = await pool.query(
        `SELECT u.id, u.login, u.avatar_url FROM sessions s JOIN users u ON u.id = s.user_id
         WHERE s.token_hash = $1 AND s.expires_at > now()`,
        [sha256(token)],
      );
      if (r.rows[0]) req.user = { id: Number(r.rows[0].id), login: r.rows[0].login, avatarUrl: r.rows[0].avatar_url };
    }
  } catch (err) {
    console.error("session lookup failed", err instanceof Error ? err.message : err);
  }
  next();
};

/** CSRF defence for cookie-authenticated writes: SameSite=Lax plus an Origin check (browsers always send Origin on POST). */
export const originGuard: RequestHandler = (req, res, next) => {
  if (["GET", "HEAD", "OPTIONS"].includes(req.method)) return next();
  const hasSession = Boolean(parseCookies(req.headers.cookie)[COOKIE]);
  const origin = req.headers.origin;
  if (hasSession && origin !== undefined && origin !== config.corsOrigin) {
    res.status(403).json({ error: "Cross-origin request refused" });
    return;
  }
  next();
};

export function requireLogin(req: Request, res: Response, next: NextFunction) {
  if (config.authRequired && !req.user) {
    res.status(401).json({ error: "Sign in with GitHub to analyse a repository.", login: "/auth/github" });
    return;
  }
  next();
}

export async function createSession(userId: number): Promise<string> {
  const token = b64url(randomBytes(32));
  await pool.query("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES ($1, $2, now() + make_interval(days => $3::int))",
    [sha256(token), userId, config.sessionDays]);
  return token;
}

export function authRouter(fetchImpl: typeof fetch = fetch): Router {
  const r = makeRouter();
  const configured = () => Boolean(config.github.clientId && config.github.clientSecret);

  r.get("/auth/github", (req, res) => {
    if (!configured()) {
      res.status(503).json({ error: "GitHub login is not configured on this server." });
      return;
    }
    const state = b64url(randomBytes(24));
    const verifier = b64url(randomBytes(32));
    const challenge = b64url(createHash("sha256").update(verifier).digest());
    setCookie(res, OAUTH_COOKIE, JSON.stringify({ state, verifier }), 600);
    const url = new URL(AUTHORIZE);
    url.search = new URLSearchParams({
      client_id: config.github.clientId,
      redirect_uri: `${config.publicUrl}/auth/github/callback`,
      state,
      code_challenge: challenge,
      code_challenge_method: "S256",
      allow_signup: "false",
      // no `scope`: the narrowest grant, public profile only
    }).toString();
    res.redirect(url.toString());
  });

  r.get("/auth/github/callback", async (req, res) => {
    const fail = (msg: string, status = 400) => {
      clearCookie(res, OAUTH_COOKIE);
      res.status(status).json({ error: msg });
    };
    if (!configured()) return fail("GitHub login is not configured on this server.", 503);
    let saved: { state?: string; verifier?: string } = {};
    try {
      saved = JSON.parse(parseCookies(req.headers.cookie)[OAUTH_COOKIE] ?? "{}");
    } catch {
      /* treated as missing */
    }
    const { code, state } = req.query;
    if (typeof code !== "string" || typeof state !== "string" || !saved.state || !saved.verifier || state !== saved.state)
      return fail("Login failed: invalid or expired state. Start again.");
    try {
      const tokenRes = await fetchImpl(TOKEN, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: config.github.clientId,
          client_secret: config.github.clientSecret,
          code,
          redirect_uri: `${config.publicUrl}/auth/github/callback`,
          code_verifier: saved.verifier,
        }),
        signal: AbortSignal.timeout(8000),
      });
      const tok = (await tokenRes.json()) as { access_token?: string };
      if (!tok.access_token) return fail("Login failed: GitHub did not accept the code.");
      const userRes = await fetchImpl(USER_API, {
        headers: { Authorization: `Bearer ${tok.access_token}`, Accept: "application/vnd.github+json", "User-Agent": "codeatlas" },
        signal: AbortSignal.timeout(8000),
      });
      const gh = (await userRes.json()) as { id?: number; login?: string; avatar_url?: string };
      if (!Number.isSafeInteger(gh.id) || typeof gh.login !== "string" || !/^[A-Za-z0-9-]{1,39}$/.test(gh.login))
        return fail("Login failed: unexpected GitHub response.", 502);
      // the access token goes out of scope here and is never persisted
      const u = await pool.query(
        `INSERT INTO users (email, name, github_id, login, avatar_url) VALUES ($1, $2, $3, $4, $5)
         ON CONFLICT (github_id) DO UPDATE SET login = EXCLUDED.login, avatar_url = EXCLUDED.avatar_url
         RETURNING id`,
        [`${gh.id}+${gh.login}@users.noreply.github.com`, gh.login, gh.id, gh.login, typeof gh.avatar_url === "string" ? gh.avatar_url.slice(0, 300) : null],
      );
      const session = await createSession(Number(u.rows[0].id));
      clearCookie(res, OAUTH_COOKIE);
      setCookie(res, COOKIE, session, config.sessionDays * 86400);
      res.redirect(config.corsOrigin);
    } catch (err) {
      console.error("oauth callback failed", err instanceof Error ? err.message : err);
      fail("Login failed. Try again.", 502);
    }
  });

  r.post("/auth/logout", async (req, res) => {
    const token = parseCookies(req.headers.cookie)[COOKIE];
    if (token) await pool.query("DELETE FROM sessions WHERE token_hash = $1", [sha256(token)]).catch(() => {});
    clearCookie(res, COOKIE);
    res.json({ ok: true });
  });

  r.get("/me", (req, res) => {
    res.json({
      user: req.user ?? null,
      loginAvailable: configured(),
      authRequired: config.authRequired,
      demoMode: config.demoMode,
      limits: { analysesPerDay: config.analysesPerUserPerDay, maxRepoMb: Math.round(config.maxRepoKb / 1024) },
      notice: "Public GitHub repositories only. Private repositories are not supported.",
    });
  });

  return r;
}
