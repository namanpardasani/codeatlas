import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import request from "supertest";
import { createHash } from "node:crypto";
import { createApp } from "./app.js";
import { config } from "./config.js";
import { pool } from "./db.js";
import { redis } from "./redis.js";
import { createSession } from "./auth.js";

vi.spyOn(redis, "xadd").mockImplementation((async () => "0-1") as never);   // never wake a real worker

let dbUp = false;
let userId = 0;
let session = "";
const saved = { ...config, github: { ...config.github } };
const FAKE_TOKEN = "gho_FAKE_ACCESS_TOKEN_MUST_NEVER_BE_STORED";

function ghFetch(over: Partial<Record<string, unknown>> = {}) {
  const calls: string[] = [];
  const impl = (async (url: string) => {
    calls.push(String(url));
    const u = String(url);
    if (u.endsWith("/login/oauth/access_token")) return new Response(JSON.stringify({ access_token: FAKE_TOKEN }), { status: 200 });
    if (u === "https://api.github.com/user") return new Response(JSON.stringify({ id: 424242, login: "octo-test", avatar_url: "https://a/x.png" }), { status: 200 });
    if (u.startsWith("https://api.github.com/repos/")) {
      if (over.repoStatus) return new Response("{}", { status: over.repoStatus as number });
      return new Response(JSON.stringify({ private: over.private ?? false, size: over.size ?? 100 }), { status: 200 });
    }
    throw new Error("unexpected fetch " + u);
  }) as unknown as typeof fetch;
  return { impl, calls };
}

beforeAll(async () => {
  try {
    await pool.query("DELETE FROM users WHERE github_id = 424242 OR email LIKE 'authtest-%'");
    const u = await pool.query("INSERT INTO users (email, login) VALUES ('authtest-a@example.com', 'authtest-a') RETURNING id");
    userId = Number(u.rows[0].id);
    session = await createSession(userId);
    dbUp = true;
  } catch {
    dbUp = false;
  }
});

beforeEach(() => {
  Object.assign(config, { authRequired: false, demoMode: false, analysesPerUserPerDay: 5, maxQueued: 20, sseMaxPerIp: 5 });
  config.github.clientId = "cid";
  config.github.clientSecret = "secret";
});

afterEach(async () => {
  if (dbUp) await pool.query("DELETE FROM repos WHERE full_name LIKE 'authtest/%'");
});

afterAll(async () => {
  if (dbUp) await pool.query("DELETE FROM users WHERE github_id = 424242 OR email LIKE 'authtest-%'");
  Object.assign(config, saved);
  await pool.end();
});

const cookie = () => `ca_session=${session}`;
const submit = (app: ReturnType<typeof createApp>, name: string, withSession = true) => {
  const r = request(app).post("/repos").send({ url: `https://github.com/authtest/${name}` });
  return withSession ? r.set("Cookie", cookie()) : r;
};

describe("GitHub OAuth", () => {
  it("redirects to GitHub with state, PKCE S256, the exact callback and NO scope", async () => {
    const res = await request(createApp()).get("/auth/github");
    expect(res.status).toBe(302);
    const u = new URL(res.headers.location!);
    expect(u.origin + u.pathname).toBe("https://github.com/login/oauth/authorize");
    expect(u.searchParams.get("client_id")).toBe("cid");
    expect(u.searchParams.get("code_challenge_method")).toBe("S256");
    expect(u.searchParams.get("code_challenge")).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(u.searchParams.get("state")!.length).toBeGreaterThanOrEqual(32);
    expect(u.searchParams.get("redirect_uri")).toBe(`${config.publicUrl}/auth/github/callback`);
    expect(u.searchParams.has("scope")).toBe(false);
    const set = String(res.headers["set-cookie"]);
    expect(set).toMatch(/ca_oauth=/);
    expect(set).toMatch(/HttpOnly/);
    expect(set).toMatch(/SameSite=Lax/);
  });

  it("says so when login is not configured", async () => {
    config.github.clientId = "";
    expect((await request(createApp()).get("/auth/github")).status).toBe(503);
    expect((await request(createApp()).get("/me")).body.loginAvailable).toBe(false);
  });

  it("completes the login, creates a hashed session and never stores the GitHub token", async ({ skip }) => {
    if (!dbUp) skip();
    const gh = ghFetch();
    const app = createApp({ fetchImpl: gh.impl });
    const start = await request(app).get("/auth/github");
    const state = new URL(start.headers.location!).searchParams.get("state")!;
    const oauthCookie = String(start.headers["set-cookie"]).split(";")[0]!;
    const cb = await request(app).get(`/auth/github/callback?code=abc&state=${state}`).set("Cookie", oauthCookie);
    expect(cb.status).toBe(302);
    const setCookies = ([] as string[]).concat(cb.headers["set-cookie"] as unknown as string[]);
    const sess = setCookies.find((c) => c.startsWith("ca_session="))!;
    expect(sess).toMatch(/HttpOnly/);
    expect(sess).toMatch(/SameSite=Lax/);
    const raw = sess.split(";")[0]!.split("=")[1]!;
    // the code verifier was sent to the token endpoint, the secret too
    expect(gh.calls[0]).toBe("https://github.com/login/oauth/access_token");
    // only the hash of the session token is stored
    const row = await pool.query("SELECT token_hash FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.github_id = 424242");
    expect(row.rows[0].token_hash).toBe(createHash("sha256").update(raw).digest("hex"));
    expect(JSON.stringify(row.rows)).not.toContain(raw);
    // the GitHub access token is nowhere in the database
    for (const t of ["users", "sessions"]) {
      const all = await pool.query(`SELECT row_to_json(t)::text AS j FROM ${t} t`);
      expect(all.rows.map((r) => r.j).join()).not.toContain(FAKE_TOKEN);
    }
    const me = await request(app).get("/me").set("Cookie", `ca_session=${raw}`);
    expect(me.body.user).toMatchObject({ login: "octo-test" });
    expect(me.body.notice).toMatch(/Public GitHub repositories only/);
    await request(app).post("/auth/logout").set("Cookie", `ca_session=${raw}`);
    expect((await request(app).get("/me").set("Cookie", `ca_session=${raw}`)).body.user).toBeNull();
  });

  it("rejects a callback with a wrong, missing or replayed state", async () => {
    const gh = ghFetch();
    const app = createApp({ fetchImpl: gh.impl });
    const start = await request(app).get("/auth/github");
    const oauthCookie = String(start.headers["set-cookie"]).split(";")[0]!;
    expect((await request(app).get("/auth/github/callback?code=abc&state=forged").set("Cookie", oauthCookie)).status).toBe(400);
    expect((await request(app).get("/auth/github/callback?code=abc&state=forged")).status).toBe(400);
    expect((await request(app).get("/auth/github/callback?state=x").set("Cookie", oauthCookie)).status).toBe(400);
    expect(gh.calls).toHaveLength(0);                    // GitHub is never contacted without a valid state
  });

  it("an expired or garbage session cookie means anonymous", async ({ skip }) => {
    if (!dbUp) skip();
    expect((await request(createApp()).get("/me").set("Cookie", "ca_session=garbage")).body.user).toBeNull();
    const old = await createSession(userId);
    await pool.query("UPDATE sessions SET expires_at = now() - interval '1 minute' WHERE user_id = $1 AND token_hash = $2", [userId, createHash("sha256").update(old).digest("hex")]);
    expect((await request(createApp()).get("/me").set("Cookie", `ca_session=${old}`)).body.user).toBeNull();
  });
});

describe("limits", () => {
  it("login is required to analyse when AUTH_REQUIRED=1", async ({ skip }) => {
    if (!dbUp) skip();
    config.authRequired = true;
    const gh = ghFetch();
    const app = createApp({ fetchImpl: gh.impl });
    const anon = await submit(app, "needs-login", false);
    expect(anon.status).toBe(401);
    expect(anon.body.error).toMatch(/Sign in/);
    expect((await submit(app, "needs-login")).status).toBe(202);
  });

  it("per-user daily cap returns 429 with Retry-After and counts by user", async ({ skip }) => {
    if (!dbUp) skip();
    await pool.query("DELETE FROM analysis_jobs WHERE requested_by = $1", [userId]);
    config.analysesPerUserPerDay = 2;
    const app = createApp({ fetchImpl: ghFetch().impl });
    expect((await submit(app, "cap-a")).status).toBe(202);
    expect((await submit(app, "cap-b")).status).toBe(202);
    const third = await submit(app, "cap-c");
    expect(third.status).toBe(429);
    expect(Number(third.headers["retry-after"])).toBeGreaterThan(0);
    expect(third.body.error).toMatch(/Daily analysis limit/);
    await pool.query("DELETE FROM analysis_jobs WHERE requested_by = $1", [userId]);
  });

  it("a full queue returns 503 with Retry-After", async ({ skip }) => {
    if (!dbUp) skip();
    config.maxQueued = 0;
    const res = await submit(createApp({ fetchImpl: ghFetch().impl }), "queue-full");
    expect(res.status).toBe(503);
    expect(res.headers["retry-after"]).toBeTruthy();
  });

  it("demo mode refuses every analysis", async ({ skip }) => {
    if (!dbUp) skip();
    config.demoMode = true;
    const res = await submit(createApp({ fetchImpl: ghFetch().impl }), "demo");
    expect(res.status).toBe(403);
    expect(res.body.error).toMatch(/read-only demo/);
  });

  it("refuses private, missing and oversized repositories before queueing anything", async ({ skip }) => {
    if (!dbUp) skip();
    await pool.query("DELETE FROM analysis_jobs WHERE requested_by = $1", [userId]);
    const priv = await submit(createApp({ fetchImpl: ghFetch({ private: true }).impl }), "priv");
    expect(priv.status).toBe(400);
    expect(priv.body.error).toMatch(/Private repositories are not supported/);
    const missing = await submit(createApp({ fetchImpl: ghFetch({ repoStatus: 404 }).impl }), "missing");
    expect(missing.status).toBe(404);
    expect(missing.body.error).toMatch(/private/i);
    const big = await submit(createApp({ fetchImpl: ghFetch({ size: config.maxRepoKb + 1 }).impl }), "big");
    expect(big.status).toBe(413);
    const n = await pool.query("SELECT count(*)::int AS n FROM repos WHERE full_name LIKE 'authtest/%'");
    expect(n.rows[0].n).toBe(0);
  });

  it("GitHub being unreachable does not block (the worker enforces the same limits)", async ({ skip }) => {
    if (!dbUp) skip();
    const down = (async () => { throw new Error("network"); }) as unknown as typeof fetch;
    expect((await submit(createApp({ fetchImpl: down }), "offline")).status).toBe(202);
  });

  it("rejects non-GitHub URLs before any network call", async () => {
    const gh = ghFetch();
    const res = await request(createApp({ fetchImpl: gh.impl })).post("/repos").set("Cookie", cookie())
      .send({ url: "https://evil.example/authtest/x" });
    expect(res.status).toBe(400);
    expect(gh.calls).toHaveLength(0);
  });

  it("caps open progress streams per client", async () => {
    config.sseMaxPerIp = 0;
    expect((await request(createApp()).get("/jobs/1/events")).status).toBe(429);
  });
});

describe("browser safety", () => {
  it("a cross-origin POST carrying a session cookie is refused (CSRF)", async ({ skip }) => {
    if (!dbUp) skip();
    const res = await request(createApp({ fetchImpl: ghFetch().impl })).post("/repos").set("Cookie", cookie())
      .set("Origin", "https://evil.example").send({ url: "https://github.com/authtest/csrf" });
    expect(res.status).toBe(403);
  });

  it("every response carries hardening headers and CORS allows only the configured origin", async () => {
    const res = await request(createApp()).get("/me").set("Origin", "https://evil.example");
    expect(res.headers["x-content-type-options"]).toBe("nosniff");
    expect(res.headers["x-frame-options"]).toBe("DENY");
    expect(res.headers["content-security-policy"]).toMatch(/default-src 'none'/);
    expect(res.headers["access-control-allow-origin"]).not.toBe("https://evil.example");
    expect(res.headers["x-powered-by"]).toBeUndefined();
  });
});
