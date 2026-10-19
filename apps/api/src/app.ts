import express from "express";
import cors from "cors";
import rateLimit from "express-rate-limit";
import { createHash } from "node:crypto";
import { z } from "zod";
import { pool } from "./db.js";
import { redis, createSubscriber } from "./redis.js";
import { config, eventsChannel } from "./config.js";
import { parseGithubUrl } from "./github.js";

const submitSchema = z.object({ url: z.string().min(1).max(200) });

const chatSchema = z.object({
  question: z.string().trim().min(1).max(1000),
  session_id: z.string().uuid().optional(),
});

const searchSchema = z.object({
  query: z.string().trim().min(1).max(500),
  mode: z.enum(["vector", "keyword", "hybrid"]).default("hybrid"),
  chunking: z.enum(["ast", "fixed"]).default("ast"),
  limit: z.number().int().min(1).max(50).default(10),
  language: z.string().max(40).optional(),
  path_prefix: z.string().max(200).optional(),
  kind: z.string().max(30).optional(),
});

export function createApp() {
  const app = express();
  app.disable("x-powered-by");
  app.use(cors({ origin: config.corsOrigin }));
  app.use(express.json({ limit: "10kb" }));

  app.get("/health", async (_req, res) => {
    try {
      await pool.query("SELECT 1");
      await redis.ping();
      res.json({ ok: true });
    } catch {
      res.status(503).json({ ok: false });
    }
  });

  // Submissions are expensive (clone + parse): tight per-IP limit.
  const submitLimiter = rateLimit({ windowMs: 60_000, limit: 10, standardHeaders: true, legacyHeaders: false });

  app.post("/repos", submitLimiter, async (req, res) => {
    const body = submitSchema.safeParse(req.body);
    const parsed = body.success ? parseGithubUrl(body.data.url) : null;
    if (!parsed) {
      res.status(400).json({ error: "Provide a public GitHub URL like https://github.com/owner/repo" });
      return;
    }

    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const repo = await client.query(
        `INSERT INTO repos (url, full_name) VALUES ($1, $2)
         ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url
         RETURNING id, url, full_name, status`,
        [parsed.url, parsed.fullName],
      );
      const repoId = repo.rows[0].id as number;
      const job = await client.query(
        `INSERT INTO analysis_jobs (repo_id) VALUES ($1) RETURNING id`,
        [repoId],
      );
      await client.query("COMMIT");
      const jobId = job.rows[0].id as number;
      // Row is the source of truth; the stream message only wakes a worker.
      await redis.xadd(config.jobStream, "*", "jobId", String(jobId));
      res.status(202).json({ repoId, jobId, repo: repo.rows[0] });
    } catch (err) {
      await client.query("ROLLBACK").catch(() => {});
      console.error(err);
      res.status(500).json({ error: "Could not create job" });
    } finally {
      client.release();
    }
  });

  app.get("/jobs/:id", async (req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
      res.status(400).json({ error: "Invalid job id" });
      return;
    }
    const r = await pool.query(
      `SELECT j.id, j.repo_id, j.status, j.stage, j.progress, j.error, j.commit_sha,
              j.created_at, j.started_at, j.finished_at, r.full_name
       FROM analysis_jobs j JOIN repos r ON r.id = j.repo_id WHERE j.id = $1`,
      [id],
    );
    if (!r.rows[0]) {
      res.status(404).json({ error: "Job not found" });
      return;
    }
    res.json(r.rows[0]);
  });

  const idParam = (v: unknown) => {
    const n = Number(v);
    return Number.isInteger(n) && n > 0 ? n : null;
  };

  app.get("/repos/:id/files", async (req, res) => {
    const id = idParam(req.params.id);
    if (!id) {
      res.status(400).json({ error: "Invalid repo id" });
      return;
    }
    const r = await pool.query(
      `SELECT f.id, f.path, f.language, f.lines, f.is_test, f.parse_status,
              (SELECT count(*)::int FROM symbols s WHERE s.file_id = f.id) AS symbol_count,
              (SELECT count(*)::int FROM imports_raw i WHERE i.file_id = f.id) AS import_count
       FROM files f WHERE f.repo_id = $1 ORDER BY f.path`,
      [id],
    );
    res.json(r.rows);
  });

  app.get("/files/:id/symbols", async (req, res) => {
    const id = idParam(req.params.id);
    if (!id) {
      res.status(400).json({ error: "Invalid file id" });
      return;
    }
    const file = await pool.query(
      "SELECT id, repo_id, path, language, parse_status, parse_error, exports FROM files WHERE id = $1",
      [id],
    );
    if (!file.rows[0]) {
      res.status(404).json({ error: "File not found" });
      return;
    }
    const [symbols, imports] = await Promise.all([
      pool.query(
        `SELECT name, kind, start_line, end_line, params, parent_name, is_exported,
                is_default_export, has_doc, signature
         FROM symbols WHERE file_id = $1 ORDER BY idx`,
        [id],
      ),
      pool.query(
        `SELECT specifier, kind, names, level, line, is_type_only, resolution, targets, package, reason
         FROM imports_raw WHERE file_id = $1 ORDER BY idx`,
        [id],
      ),
    ]);
    res.json({ file: file.rows[0], symbols: symbols.rows, imports: imports.rows });
  });

  // Dependency graph. mode=files: file nodes (capped, most important first); mode=folders: one
  // node per folder with aggregated edges, always small enough to draw.
  const DEFAULT_GRAPH_LIMIT = 300;
  const MAX_GRAPH_LIMIT = 1000;

  app.get("/repos/:id/graph", async (req, res) => {
    const id = idParam(req.params.id);
    if (!id) {
      res.status(400).json({ error: "Invalid repo id" });
      return;
    }
    const mode = req.query.mode === "folders" ? "folders" : "files";
    const requested = Number(req.query.limit ?? DEFAULT_GRAPH_LIMIT);
    const limit = Number.isInteger(requested) && requested > 0 ? Math.min(requested, MAX_GRAPH_LIMIT) : DEFAULT_GRAPH_LIMIT;

    if (mode === "folders") {
      const [nodes, edges] = await Promise.all([
        pool.query(
          `SELECT module AS id, count(*)::int AS files,
                  count(*) FILTER (WHERE cycle_idx IS NOT NULL)::int AS files_in_cycles,
                  sum(pagerank) AS pagerank
           FROM files WHERE repo_id = $1 AND module IS NOT NULL
           GROUP BY module ORDER BY sum(pagerank) DESC`,
          [id],
        ),
        pool.query(
          `SELECT from_module AS source, to_module AS target, edge_count AS count
           FROM module_edges WHERE repo_id = $1 AND from_module <> to_module
           ORDER BY from_module, to_module`,
          [id],
        ),
      ]);
      const internal = await pool.query(
        "SELECT from_module AS module, edge_count FROM module_edges WHERE repo_id = $1 AND from_module = to_module",
        [id],
      );
      const internalBy = new Map(internal.rows.map((r) => [r.module, r.edge_count]));
      res.json({
        mode,
        truncated: false,
        total_nodes: nodes.rows.length,
        nodes: nodes.rows.map((n) => ({ ...n, internal_edges: internalBy.get(n.id) ?? 0 })),
        edges: edges.rows,
        cycles: [],
      });
      return;
    }

    const total = await pool.query(
      "SELECT count(*)::int AS n FROM files WHERE repo_id = $1 AND module IS NOT NULL",
      [id],
    );
    // Files in cycles first, then by centrality: the interesting part survives the cap.
    const nodes = await pool.query(
      `SELECT id, path, module, fan_in, fan_out, pagerank, cycle_idx
       FROM files WHERE repo_id = $1 AND module IS NOT NULL
       ORDER BY (cycle_idx IS NOT NULL) DESC, pagerank DESC, path LIMIT $2`,
      [id, limit],
    );
    const ids = nodes.rows.map((n) => n.id);
    const [edges, cycles] = await Promise.all([
      pool.query(
        `SELECT from_file_id AS source, to_file_id AS target, kinds FROM dependencies
         WHERE repo_id = $1 AND from_file_id = ANY($2::bigint[]) AND to_file_id = ANY($2::bigint[])
         ORDER BY from_file_id, to_file_id`,
        [id, ids],
      ),
      pool.query(
        "SELECT cycle_idx AS id, size, file_ids FROM dependency_cycles WHERE repo_id = $1 ORDER BY cycle_idx",
        [id],
      ),
    ]);
    res.json({
      mode,
      truncated: total.rows[0].n > nodes.rows.length,
      total_nodes: total.rows[0].n,
      nodes: nodes.rows,
      edges: edges.rows,
      cycles: cycles.rows,
    });
  });

  // What a file depends on and what depends on it (for clicking a node in the graph).
  app.get("/files/:id/graph", async (req, res) => {
    const id = idParam(req.params.id);
    if (!id) {
      res.status(400).json({ error: "Invalid file id" });
      return;
    }
    const file = await pool.query(
      "SELECT id, repo_id, path, module, fan_in, fan_out, pagerank, cycle_idx FROM files WHERE id = $1",
      [id],
    );
    const f = file.rows[0];
    if (!f) {
      res.status(404).json({ error: "File not found" });
      return;
    }
    const [imports, importedBy, cycle] = await Promise.all([
      pool.query(
        `SELECT f.id, f.path, d.kinds FROM dependencies d JOIN files f ON f.id = d.to_file_id
         WHERE d.from_file_id = $1 ORDER BY f.path`,
        [id],
      ),
      pool.query(
        `SELECT f.id, f.path, d.kinds FROM dependencies d JOIN files f ON f.id = d.from_file_id
         WHERE d.to_file_id = $1 ORDER BY f.path`,
        [id],
      ),
      f.cycle_idx === null
        ? Promise.resolve({ rows: [] as { id: string; path: string }[] })
        : pool.query(
            `SELECT id, path FROM files WHERE repo_id = $1 AND cycle_idx = $2 ORDER BY path`,
            [f.repo_id, f.cycle_idx],
          ),
    ]);
    res.json({ file: f, imports: imports.rows, imported_by: importedBy.rows, cycle: cycle.rows });
  });

  // ---- Search (Day 5): validated here, executed by the Python service that owns the embedding model ----
  const searchLimiter = rateLimit({ windowMs: 60_000, limit: 60, standardHeaders: true, legacyHeaders: false });

  app.post("/repos/:id/search", searchLimiter, async (req, res) => {
    const id = idParam(req.params.id);
    if (!id) {
      res.status(400).json({ error: "Invalid repo id" });
      return;
    }
    const body = searchSchema.safeParse(req.body ?? {});
    if (!body.success) {
      res.status(400).json({ error: "Invalid search request", details: body.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`) });
      return;
    }
    const exists = await pool.query("SELECT 1 FROM repos WHERE id = $1", [id]);
    if (exists.rowCount === 0) {
      res.status(404).json({ error: "Repo not found" });
      return;
    }
    try {
      const upstream = await fetch(`${config.searchUrl}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_id: id, ...body.data }),
        signal: AbortSignal.timeout(20_000),
      });
      const payload = await upstream.json();
      res.status(upstream.status >= 500 ? 502 : upstream.status).json(payload);
    } catch (err) {
      console.error("search service error", err);
      res.status(503).json({ error: "Search service unavailable" });
    }
  });

  // ---- Chat (Day 6): sessions + history live here; retrieval, LLM and citation checks run in the Python service ----
  const chatLimiter = rateLimit({ windowMs: 60_000, limit: 20, standardHeaders: true, legacyHeaders: false });
  const clientKey = (ip: string | undefined) =>
    createHash("sha256").update(`${config.clientSalt}:${ip ?? "unknown"}`).digest("hex").slice(0, 24);

  app.post("/repos/:id/chat", chatLimiter, async (req, res) => {
    const id = idParam(req.params.id);
    if (!id) {
      res.status(400).json({ error: "Invalid repo id" });
      return;
    }
    const body = chatSchema.safeParse(req.body ?? {});
    if (!body.success) {
      res.status(400).json({ error: "Invalid chat request", details: body.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`) });
      return;
    }
    const { question, session_id } = body.data;
    const client = clientKey(req.ip);
    const repo = await pool.query("SELECT id FROM repos WHERE id = $1", [id]);
    if (repo.rowCount === 0) {
      res.status(404).json({ error: "Repo not found" });
      return;
    }

    let sessionId: number;
    let publicId: string;
    if (session_id) {
      const s = await pool.query("SELECT id, public_id FROM chat_sessions WHERE public_id = $1 AND repo_id = $2", [session_id, id]);
      if (s.rowCount === 0) {
        res.status(404).json({ error: "Chat session not found" });
        return;
      }
      sessionId = Number(s.rows[0].id);
      publicId = s.rows[0].public_id;
    } else {
      const s = await pool.query(
        "INSERT INTO chat_sessions (repo_id, client_key, title) VALUES ($1, $2, $3) RETURNING id, public_id",
        [id, client, question.slice(0, 80)],
      );
      sessionId = Number(s.rows[0].id);
      publicId = s.rows[0].public_id;
    }

    // earlier turns for follow-ups: (question, verified answer) pairs, oldest first
    const prior = await pool.query(
      "SELECT role, content FROM chat_messages WHERE session_id = $1 AND status IS DISTINCT FROM 'error' ORDER BY id DESC LIMIT 6",
      [sessionId],
    );
    const history: { q: string; a: string }[] = [];
    const chronological = prior.rows.reverse();
    for (let i = 0; i < chronological.length - 1; i++) {
      if (chronological[i].role === "user" && chronological[i + 1].role === "assistant") {
        history.push({ q: chronological[i].content, a: chronological[i + 1].content });
      }
    }
    await pool.query("INSERT INTO chat_messages (session_id, role, content) VALUES ($1, 'user', $2)", [sessionId, question]);

    res.set({ "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive", "X-Accel-Buffering": "no" });
    res.flushHeaders();
    const send = (type: string, data: unknown) => res.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    send("session", { session_id: publicId });

    const abort = new AbortController();
    res.on("close", () => abort.abort());   // browser went away: stop the upstream (and the LLM call)
    let final: Record<string, unknown> | null = null;
    let errored: { message: string; kind: string } | null = null;
    let retrieval: Record<string, unknown> | null = null;
    try {
      const upstream = await fetch(`${config.searchUrl}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_id: id, question, history, client_key: client }),
        signal: AbortSignal.any([abort.signal, AbortSignal.timeout(180_000)]),
      });
      if (!upstream.ok || !upstream.body) throw new Error(`upstream ${upstream.status}`);
      const decoder = new TextDecoder();
      let buffer = "";
      for await (const chunk of upstream.body as unknown as AsyncIterable<Uint8Array>) {
        buffer += decoder.decode(chunk, { stream: true });
        let nl: number;
        while ((nl = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (!line) continue;
          const ev = JSON.parse(line) as { type: string } & Record<string, unknown>;
          if (ev.type === "final") final = ev;
          if (ev.type === "retrieval") retrieval = ev;
          if (ev.type === "error") errored = { message: String(ev.message), kind: String(ev.kind) };
          send(ev.type, ev);
        }
      }
    } catch (err) {
      if (!abort.signal.aborted) {
        console.error("chat upstream error", err);
        errored = { message: "The answer service is unavailable.", kind: "unavailable" };
        send("error", { type: "error", ...errored, retry_after: null });
      }
    }
    try {
      if (final) {
        await pool.query(
          `INSERT INTO chat_messages (session_id, role, content, status, citations, retrieval, model, usage)
           VALUES ($1, 'assistant', $2, $3, $4, $5, $6, $7)`,
          [sessionId, String(final.answer), final.status, JSON.stringify(final.citations ?? []),
           JSON.stringify({ evidence: (retrieval as { evidence?: unknown } | null)?.evidence ?? null, retrieved: final.retrieved ?? final.closest ?? [],
                            query: (retrieval as { query?: unknown } | null)?.query ?? null, claims: final.claims ?? [], issues: final.issues ?? [] }),
           final.model ?? null, JSON.stringify(final.usage ?? null)],
        );
      } else if (errored) {
        await pool.query("INSERT INTO chat_messages (session_id, role, content, status) VALUES ($1, 'assistant', $2, 'error')", [sessionId, errored.message]);
      }
      await pool.query("UPDATE chat_sessions SET updated_at = now() WHERE id = $1", [sessionId]);
    } catch (err) {
      console.error("could not store chat message", err);
    }
    res.end();
  });

  app.get("/chat/sessions/:publicId", async (req, res) => {
    const parsed = z.string().uuid().safeParse(req.params.publicId);
    if (!parsed.success) {
      res.status(400).json({ error: "Invalid session id" });
      return;
    }
    const s = await pool.query("SELECT id, repo_id, title, created_at FROM chat_sessions WHERE public_id = $1", [parsed.data]);
    if (s.rowCount === 0) {
      res.status(404).json({ error: "Chat session not found" });
      return;
    }
    const m = await pool.query(
      "SELECT id, role, content, status, citations, model, created_at FROM chat_messages WHERE session_id = $1 ORDER BY id",
      [s.rows[0].id],
    );
    res.json({ session: { id: parsed.data, repo_id: s.rows[0].repo_id, title: s.rows[0].title }, messages: m.rows });
  });

  // Text of an indexed file, for the code viewer (citations open it at their lines).
  app.get("/repos/:id/file", async (req, res) => {
    const id = idParam(req.params.id);
    const path = typeof req.query.path === "string" ? req.query.path : "";
    if (!id || !path || path.length > 500) {
      res.status(400).json({ error: "repo id and path are required" });
      return;
    }
    const r = await pool.query(
      `SELECT f.id, f.path, f.language, c.content FROM files f JOIN file_contents c ON c.file_id = f.id
       WHERE f.repo_id = $1 AND f.path = $2`,
      [id, path],
    );
    if (r.rowCount === 0) {
      res.status(404).json({ error: "File not found or not indexed" });
      return;
    }
    res.json({ id: r.rows[0].id, path: r.rows[0].path, language: r.rows[0].language, content: r.rows[0].content });
  });

  // ---- Hotspots, co-change and per-file metrics (Day 4) ----------------------------------
  const HOTSPOT_SORTS: Record<string, string> = {
    score: "f.hotspot_score", complexity: "f.max_complexity", total_complexity: "f.total_complexity",
    churn: "f.churn", commits_total: "f.commits_total", authors: "f.authors", fan_in: "f.fan_in",
    duplication: "f.dup_ratio", lines: "f.lines", path: "f.path", last_modified: "f.last_modified",
  };

  app.get("/repos/:id/hotspots", async (req, res) => {
    const id = idParam(req.params.id);
    if (!id) {
      res.status(400).json({ error: "Invalid repo id" });
      return;
    }
    const n = Number(req.query.limit ?? 50);
    const limit = Number.isInteger(n) && n > 0 ? Math.min(n, 500) : 50;
    const dir = req.query.dir === "asc" ? "ASC" : "DESC";

    const meta = await pool.query(
      `SELECT count(*)::int AS total, count(f.hotspot_score)::int AS scored
       FROM files f WHERE f.repo_id = $1 AND f.module IS NOT NULL AND NOT f.is_test`,
      [id],
    );
    const scored = meta.rows[0].scored > 0;
    // No formula yet -> "score" cannot sort anything: fall back to raw complexity.
    let sort = typeof req.query.sort === "string" && req.query.sort in HOTSPOT_SORTS ? req.query.sort : "score";
    if (sort === "score" && !scored) sort = "complexity";

    const [rows, job] = await Promise.all([
      pool.query(
        `SELECT f.id, f.path, f.language, f.lines, f.code_lines, f.comment_ratio, f.hotspot_score, f.hotspot_reasons,
                f.max_complexity, f.total_complexity, f.max_nesting, f.longest_function, f.function_count,
                f.churn, f.commits_total, f.authors, f.last_modified, f.fan_in, f.cycle_idx, f.has_test, f.test_file,
                f.dup_ratio,
                (SELECT c.size FROM dependency_cycles c WHERE c.repo_id = f.repo_id AND c.cycle_idx = f.cycle_idx) AS cycle_size
         FROM files f WHERE f.repo_id = $1 AND f.module IS NOT NULL AND NOT f.is_test
         ORDER BY ${HOTSPOT_SORTS[sort]} ${dir} NULLS LAST, f.path LIMIT $2`,
        [id, limit],
      ),
      pool.query(
        `SELECT history_commits, history_window_days, history_truncated FROM analysis_jobs
         WHERE repo_id = $1 AND status = 'done' ORDER BY id DESC LIMIT 1`,
        [id],
      ),
    ]);
    const j = job.rows[0];
    res.json({
      scored,
      sort,
      dir: dir.toLowerCase(),
      total: meta.rows[0].total,
      history: {
        available: (j?.history_commits ?? 0) > 0,
        commits: j?.history_commits ?? 0,
        window_days: j?.history_window_days ?? null,
        truncated: j?.history_truncated ?? false,
      },
      items: rows.rows,
    });
  });

  app.get("/repos/:id/cochange", async (req, res) => {
    const id = idParam(req.params.id);
    if (!id) {
      res.status(400).json({ error: "Invalid repo id" });
      return;
    }
    const n = Number(req.query.limit ?? 20);
    const limit = Number.isInteger(n) && n > 0 ? Math.min(n, 200) : 20;
    const r = await pool.query(
      `SELECT a.path AS file_a, b.path AS file_b, x.count, x.coupling
       FROM file_cochange x JOIN files a ON a.id = x.file_a_id JOIN files b ON b.id = x.file_b_id
       WHERE x.repo_id = $1 ORDER BY x.count DESC, x.coupling DESC, a.path LIMIT $2`,
      [id, limit],
    );
    res.json(r.rows);
  });

  app.get("/files/:id/metrics", async (req, res) => {
    const id = idParam(req.params.id);
    if (!id) {
      res.status(400).json({ error: "Invalid file id" });
      return;
    }
    const file = await pool.query(
      `SELECT id, repo_id, path, language, lines, code_lines, comment_lines, comment_ratio, total_complexity,
              max_complexity, max_nesting, function_count, longest_function, churn, commits_total, authors,
              last_modified, dup_lines, dup_ratio, has_test, test_file, hotspot_score, hotspot_reasons,
              hotspot_detail, cycle_idx, fan_in, fan_out, pagerank
       FROM files WHERE id = $1`,
      [id],
    );
    const f = file.rows[0];
    if (!f) {
      res.status(404).json({ error: "File not found" });
      return;
    }
    const [functions, duplicates, cochange] = await Promise.all([
      pool.query(
        `SELECT name, kind, parent_name, start_line, end_line, (end_line - start_line + 1) AS length,
                complexity, max_nesting, param_count
         FROM symbols WHERE file_id = $1 AND complexity IS NOT NULL ORDER BY complexity DESC, start_line`,
        [id],
      ),
      pool.query(
        `SELECT b.group_idx AS group_id, b.start_line, b.end_line, g.lines, g.total_locations,
                (SELECT json_agg(json_build_object('path', f2.path, 'start_line', b2.start_line, 'end_line', b2.end_line)
                                 ORDER BY f2.path, b2.start_line)
                 FROM duplicate_blocks b2 JOIN files f2 ON f2.id = b2.file_id
                 WHERE b2.repo_id = b.repo_id AND b2.group_idx = b.group_idx AND NOT (b2.file_id = b.file_id AND b2.start_line = b.start_line)) AS others
         FROM duplicate_blocks b JOIN duplicate_groups g ON g.repo_id = b.repo_id AND g.idx = b.group_idx
         WHERE b.file_id = $1 ORDER BY b.start_line`,
        [id],
      ),
      pool.query(
        `SELECT p.path, x.count, x.coupling FROM file_cochange x
         JOIN files p ON p.id = CASE WHEN x.file_a_id = $1 THEN x.file_b_id ELSE x.file_a_id END
         WHERE x.file_a_id = $1 OR x.file_b_id = $1 ORDER BY x.count DESC, x.coupling DESC, p.path LIMIT 10`,
        [id],
      ),
    ]);
    res.json({ file: f, functions: functions.rows, duplicates: duplicates.rows, cochange: cochange.rows });
  });

  // Server-Sent Events: current state first, then live updates published by the worker.
  app.get("/jobs/:id/events", async (req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
      res.status(400).json({ error: "Invalid job id" });
      return;
    }
    res.set({
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    res.flushHeaders();

    const send = (data: unknown) => res.write(`data: ${JSON.stringify(data)}\n\n`);

    const sub = createSubscriber();
    await sub.subscribe(eventsChannel(id));
    sub.on("message", (_ch, message) => {
      res.write(`data: ${message}\n\n`);
      try {
        const s = JSON.parse(message).status;
        if (s === "done" || s === "failed") res.end();
      } catch {
        /* ignore malformed */
      }
    });

    // Subscribe before reading the row so no update is missed in between.
    const r = await pool.query(
      "SELECT id, status, stage, progress, error FROM analysis_jobs WHERE id = $1",
      [id],
    );
    if (r.rows[0]) {
      send(r.rows[0]);
      if (["done", "failed"].includes(r.rows[0].status)) res.end();
    } else {
      send({ status: "failed", error: "Job not found" });
      res.end();
    }

    const ping = setInterval(() => res.write(": ping\n\n"), 15_000);
    req.on("close", () => {
      clearInterval(ping);
      sub.disconnect();
    });
  });

  return app;
}
