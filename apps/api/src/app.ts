import express from "express";
import cors from "cors";
import rateLimit from "express-rate-limit";
import { z } from "zod";
import { pool } from "./db.js";
import { redis, createSubscriber } from "./redis.js";
import { config, eventsChannel } from "./config.js";
import { parseGithubUrl } from "./github.js";

const submitSchema = z.object({ url: z.string().min(1).max(200) });

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
