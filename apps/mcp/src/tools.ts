import { config } from "./config.js";
import type { Db } from "./db.js";
import { clean, fit, pack } from "./output.js";
import type { RepoRef } from "./auth.js";

export interface Ctx {
  db: Db;
  repo: RepoRef;
  /** injectable for tests */
  fetchImpl?: typeof fetch;
}

const like = (s: string) => s.replace(/[\\%_]/g, (c) => `\\${c}`);
// hotspot_reasons are objects { text, factor, points, severity }; only the human sentence is useful to an agent.
const reasons = (v: unknown): string[] =>
  (Array.isArray(v) ? v : []).slice(0, 4).map((x: any) => clean(typeof x === "string" ? x : x?.text ?? "", 220));

const STOP = new Set("the and are for how what where which does with from that this into when who why can you use used not has have was were".split(" "));
// OR-query for the SQL fallback: only plain identifier-like words, so nothing can be injected into tsquery syntax.
const orQuery = (q: string) =>
  [...new Set((q.toLowerCase().match(/[a-z_][a-z0-9_]{2,}/g) ?? []).filter((w) => !STOP.has(w)))].slice(0, 8).join(" | ");

const meta = (r: RepoRef) => ({ repo: r.fullName, commit: r.commit?.slice(0, 7) ?? null });

// ---------------------------------------------------------------------------------------------------------------
export async function getArchitecture({ db, repo }: Ctx) {
  const id = repo.id;
  const [job, facts, summary, modules, edges, cycles, central, langs, counts] = await Promise.all([
    db.query(
      `SELECT commit_sha, finished_at, files_total FROM analysis_jobs WHERE repo_id = $1 AND status = 'done' ORDER BY id DESC LIMIT 1`,
      [id],
    ),
    db.query("SELECT facts FROM repo_facts WHERE repo_id = $1", [id]),
    db.query(
      "SELECT summary, source, model FROM doc_summaries WHERE repo_id = $1 AND target_type = 'repo' AND target_ref = ''",
      [id],
    ),
    db.query(
      `SELECT module, count(*)::int AS files, round(sum(pagerank)::numeric, 3)::float AS centrality,
              count(*) FILTER (WHERE cycle_idx IS NOT NULL)::int AS files_in_cycles
       FROM files WHERE repo_id = $1 AND module IS NOT NULL GROUP BY module ORDER BY sum(pagerank) DESC LIMIT 15`,
      [id],
    ),
    db.query(
      `SELECT from_module, to_module, edge_count FROM module_edges
       WHERE repo_id = $1 AND from_module <> to_module ORDER BY edge_count DESC, from_module, to_module LIMIT 20`,
      [id],
    ),
    db.query(
      `SELECT c.cycle_idx, c.size,
              (SELECT array_agg(path ORDER BY path) FROM (SELECT f.path FROM files f WHERE f.repo_id = c.repo_id AND f.cycle_idx = c.cycle_idx ORDER BY f.path LIMIT 6) x) AS sample
       FROM dependency_cycles c WHERE c.repo_id = $1 ORDER BY c.size DESC, c.cycle_idx LIMIT 5`,
      [id],
    ),
    db.query(
      `SELECT path, fan_in, fan_out, round(pagerank::numeric, 3)::float AS centrality FROM files
       WHERE repo_id = $1 AND module IS NOT NULL AND NOT is_test ORDER BY pagerank DESC, path LIMIT 8`,
      [id],
    ),
    db.query(
      `SELECT language, count(*)::int AS files, sum(lines)::int AS lines FROM files
       WHERE repo_id = $1 AND language IS NOT NULL GROUP BY language ORDER BY sum(lines) DESC LIMIT 8`,
      [id],
    ),
    db.query(
      `SELECT count(*)::int AS files, (SELECT count(*)::int FROM symbols WHERE repo_id = $1) AS symbols,
              (SELECT count(*)::int FROM dependencies WHERE repo_id = $1) AS dependencies FROM files WHERE repo_id = $1`,
      [id],
    ),
  ]);
  const f = (facts.rows[0]?.facts ?? {}) as Record<string, any>;
  const s = summary.rows[0];
  return fit(
    {
      ...meta(repo),
      analysed_at: job.rows[0]?.finished_at ?? null,
      totals: counts.rows[0],
      summary: s ? { text: clean(s.summary, 900), source: s.source === "llm" ? "model-written, screened" : "extractive (no model)" } : null,
      languages: langs.rows,
      entry_points: (f.entry_points ?? []).slice(0, 8).map((e: any) => ({ path: clean(e.path, 200), why: clean(e.why, 120) })),
      how_to_run: (f.run_hints ?? []).slice(0, 4).map((h: any) => ({
        source: clean(h.source, 120),
        title: clean(h.title, 80),
        commands: (h.commands ?? []).slice(0, 6).map((c: string) => clean(c, 160)),
      })),
      modules: modules.rows.map((m) => ({ ...m, module: clean(m.module, 200) })),
      module_dependencies: edges.rows.map((e) => ({ from: clean(e.from_module, 200), to: clean(e.to_module, 200), imports: e.edge_count })),
      dependency_cycles: cycles.rows.map((c) => ({ id: c.cycle_idx, files: c.size, sample: (c.sample ?? []).map((p: string) => clean(p, 200)) })),
      most_central_files: central.rows.map((r) => ({ ...r, path: clean(r.path, 200) })),
      next: "Use find_symbol, get_dependencies, explain_file or search_code to drill down.",
    },
    ["module_dependencies", "how_to_run", "dependency_cycles", "modules", "most_central_files", "entry_points", "languages"],
  );
}

// ---------------------------------------------------------------------------------------------------------------
export async function findSymbol({ db, repo }: Ctx, a: { name: string; kind?: string; exported_only?: boolean; limit: number; offset: number }) {
  const parts = a.name.split(".");
  const last = parts[parts.length - 1]!;
  const parent = parts.length > 1 ? parts[parts.length - 2]! : null;
  const r = await db.query(
    `SELECT s.name, s.kind, f.path, s.start_line, s.end_line, s.parent_name, s.is_exported, s.signature, s.complexity,
            CASE WHEN s.name = $2 THEN 0 WHEN lower(s.name) = lower($2) THEN 1 WHEN s.name ILIKE $3 || '%' THEN 2 ELSE 3 END AS rank
     FROM symbols s JOIN files f ON f.id = s.file_id
     WHERE s.repo_id = $1 AND s.name ILIKE '%' || $3 || '%'
       AND ($4::text IS NULL OR s.kind = $4) AND (NOT $5 OR s.is_exported)
       AND ($6::text IS NULL OR s.parent_name ILIKE $6)
     ORDER BY rank, f.is_test, f.path, s.start_line LIMIT $7 OFFSET $8`,
    [repo.id, last, like(last), a.kind ?? null, a.exported_only ?? false, parent ? like(parent) : null, a.limit + 1, a.offset],
  );
  const rows = r.rows.slice(0, a.limit);
  const items = rows.map((s) => ({
    name: clean(s.name, 120),
    kind: s.kind,
    path: clean(s.path, 200),
    lines: [s.start_line, s.end_line],
    parent: s.parent_name ? clean(s.parent_name, 120) : undefined,
    exported: s.is_exported,
    signature: clean(s.signature, 200),
    complexity: s.complexity ?? undefined,
    match: ["exact", "case-insensitive", "prefix", "substring"][s.rank],
  }));
  return pack({ ...meta(repo), query: a.name }, items, a.offset, r.rows.length > a.limit);
}

// ---------------------------------------------------------------------------------------------------------------
export class UserError extends Error {}

export async function findFile(db: Db, repo: RepoRef, path: string) {
  const exact = await db.query("SELECT id, path FROM files WHERE repo_id = $1 AND path = $2", [repo.id, path]);
  if (exact.rows[0]) return exact.rows[0] as { id: string; path: string };
  const suffix = await db.query(
    "SELECT id, path FROM files WHERE repo_id = $1 AND path ILIKE '%/' || $2 ESCAPE '\\' ORDER BY path LIMIT 6",
    [repo.id, like(path)],
  );
  if (suffix.rows.length === 1) return suffix.rows[0] as { id: string; path: string };
  if (suffix.rows.length > 1)
    throw new UserError(`"${clean(path, 100)}" is ambiguous. Candidates: ${suffix.rows.slice(0, 5).map((r) => clean(r.path, 150)).join(", ")}. Pass the full path.`);
  throw new UserError(`No file "${clean(path, 100)}" in ${repo.fullName}. Use find_symbol or search_code to locate it.`);
}

export async function getDependencies({ db, repo }: Ctx, a: { file: string; direction: "imports" | "imported_by" | "both"; limit: number; offset: number }) {
  const file = await findFile(db, repo, a.file);
  const want = (d: string) => a.direction === "both" || a.direction === d;
  const list = async (outgoing: boolean) => {
    const [from, to] = outgoing ? ["from_file_id", "to_file_id"] : ["to_file_id", "from_file_id"];
    const r = await db.query(
      `SELECT f.path, d.kinds, count(*) OVER ()::int AS total FROM dependencies d JOIN files f ON f.id = d.${to}
       WHERE d.repo_id = $1 AND d.${from} = $2 ORDER BY f.path LIMIT $3 OFFSET $4`,
      [repo.id, file.id, a.limit, a.offset],
    );
    return { total: r.rows[0]?.total ?? 0, rows: r.rows.map((x) => ({ path: clean(x.path, 200), via: x.kinds })) };
  };
  const [out, inc, ext, cycle] = await Promise.all([
    want("imports") ? list(true) : null,
    want("imported_by") ? list(false) : null,
    want("imports")
      ? db.query(
          `SELECT package, count(*)::int AS n FROM imports_raw WHERE file_id = $1 AND resolution = 'external' AND package IS NOT NULL
           GROUP BY package ORDER BY package LIMIT 40`,
          [file.id],
        )
      : null,
    db.query(
      `SELECT c.cycle_idx, c.size FROM files f JOIN dependency_cycles c ON c.repo_id = f.repo_id AND c.cycle_idx = f.cycle_idx WHERE f.id = $1`,
      [file.id],
    ),
  ]);
  const more = (x: { total: number; rows: unknown[] } | null) => (x ? a.offset + x.rows.length < x.total : false);
  const doc: Record<string, unknown> = {
    ...meta(repo),
    file: clean(file.path, 200),
    in_cycle: cycle.rows[0] ? { id: cycle.rows[0].cycle_idx, files: cycle.rows[0].size } : null,
    ...(out ? { imports: out.rows, imports_total: out.total } : {}),
    ...(ext ? { external_packages: ext.rows.map((r) => clean(r.package, 80)) } : {}),
    ...(inc ? { imported_by: inc.rows, imported_by_total: inc.total } : {}),
  };
  const result = fit(doc, ["imported_by", "imports", "external_packages"]);
  if (more(out) || more(inc) || result.truncated) {
    result.truncated = true;
    result.next_offset = a.offset + a.limit;
    result.hint = `Lists are cut. Call again with offset=${a.offset + a.limit} (or use a smaller limit / one direction).`;
  }
  return result;
}

// ---------------------------------------------------------------------------------------------------------------
export async function getHotspots({ db, repo }: Ctx, a: { limit: number; offset: number }) {
  const [rows, job, cnt] = await Promise.all([
    db.query(
      `SELECT path, hotspot_score, hotspot_reasons, max_complexity, lines, churn, authors, fan_in, cycle_idx, has_test
       FROM files WHERE repo_id = $1 AND module IS NOT NULL AND NOT is_test AND hotspot_score IS NOT NULL
       ORDER BY hotspot_score DESC, path LIMIT $2 OFFSET $3`,
      [repo.id, a.limit + 1, a.offset],
    ),
    db.query(
      `SELECT history_commits, history_window_days FROM analysis_jobs WHERE repo_id = $1 AND status = 'done' ORDER BY id DESC LIMIT 1`,
      [repo.id],
    ),
    db.query("SELECT count(hotspot_score)::int AS n FROM files WHERE repo_id = $1 AND module IS NOT NULL AND NOT is_test", [repo.id]),
  ]);
  const items = rows.rows.slice(0, a.limit).map((r) => ({
    path: clean(r.path, 200),
    score: Math.round(r.hotspot_score * 1000) / 1000,
    why: reasons(r.hotspot_reasons),
    max_complexity: r.max_complexity,
    lines: r.lines,
    churn: r.churn,
    fan_in: r.fan_in,
    in_cycle: r.cycle_idx !== null,
    has_test: r.has_test,
  }));
  const h = job.rows[0];
  return pack(
    {
      ...meta(repo),
      about: "Score combines complexity, churn, fan-in, cycles, duplication and missing tests; higher = riskier to change.",
      history: h?.history_commits ? { commits: h.history_commits, window_days: h.history_window_days } : "unavailable (churn not used)",
    },
    items,
    a.offset,
    rows.rows.length > a.limit,
    cnt.rows[0].n,
  );
}

// ---------------------------------------------------------------------------------------------------------------
export async function explainFile({ db, repo }: Ctx, a: { path: string }) {
  const file = await findFile(db, repo, a.path);
  const [m, doc, syms, outs, ins, dup, co] = await Promise.all([
    db.query(
      `SELECT language, lines, code_lines, comment_ratio, total_complexity, max_complexity, function_count, longest_function,
              churn, commits_total, authors, last_modified, dup_ratio, has_test, test_file, hotspot_score, hotspot_reasons,
              cycle_idx, fan_in, fan_out, module, parse_status
       FROM files WHERE id = $1`,
      [file.id],
    ),
    db.query(
      "SELECT summary, source, model, commit_sha, updated_at FROM doc_summaries WHERE repo_id = $1 AND target_type = 'file' AND target_ref = $2",
      [repo.id, file.path],
    ),
    db.query(
      `SELECT name, kind, start_line, end_line, parent_name, is_exported, signature, complexity,
              count(*) OVER ()::int AS total FROM symbols WHERE file_id = $1
       ORDER BY is_exported DESC, start_line LIMIT 40`,
      [file.id],
    ),
    db.query(
      `SELECT f.path FROM dependencies d JOIN files f ON f.id = d.to_file_id WHERE d.from_file_id = $1 ORDER BY f.path LIMIT 12`,
      [file.id],
    ),
    db.query(
      `SELECT f.path, count(*) OVER ()::int AS total FROM dependencies d JOIN files f ON f.id = d.from_file_id WHERE d.to_file_id = $1 ORDER BY f.path LIMIT 12`,
      [file.id],
    ),
    db.query("SELECT count(*)::int AS n FROM duplicate_blocks WHERE file_id = $1", [file.id]),
    db.query(
      `SELECT p.path, x.count FROM file_cochange x
       JOIN files p ON p.id = CASE WHEN x.file_a_id = $1 THEN x.file_b_id ELSE x.file_a_id END
       WHERE x.file_a_id = $1 OR x.file_b_id = $1 ORDER BY x.count DESC, p.path LIMIT 5`,
      [file.id],
    ),
  ]);
  const f = m.rows[0]!;
  const d = doc.rows[0];
  return fit(
    {
      ...meta(repo),
      path: clean(file.path, 200),
      language: f.language,
      summary: d
        ? {
            text: clean(d.summary, 900),
            source: d.source === "llm" ? "model-written, screened, may contain mistakes" : "extractive (no model)",
            generated_from_commit: d.commit_sha?.slice(0, 7) ?? null,
          }
        : "No generated summary for this file.",
      metrics: {
        lines: f.lines, code_lines: f.code_lines, functions: f.function_count, max_complexity: f.max_complexity,
        longest_function: f.longest_function, churn: f.churn, authors: f.authors, last_modified: f.last_modified,
        duplicated_ratio: f.dup_ratio, hotspot_score: f.hotspot_score === null ? null : Math.round(f.hotspot_score * 1000) / 1000,
        hotspot_reasons: reasons(f.hotspot_reasons),
        duplicate_blocks: dup.rows[0].n, fan_in: f.fan_in, fan_out: f.fan_out, in_cycle: f.cycle_idx !== null,
        has_test: f.has_test, test_file: f.test_file ? clean(f.test_file, 200) : null,
      },
      module: f.module,
      symbols_total: syms.rows[0]?.total ?? 0,
      symbols: syms.rows.map((s) => ({
        name: clean(s.name, 100), kind: s.kind, lines: [s.start_line, s.end_line],
        parent: s.parent_name ? clean(s.parent_name, 100) : undefined, exported: s.is_exported,
        signature: clean(s.signature, 160), complexity: s.complexity ?? undefined,
      })),
      imports: outs.rows.map((r) => clean(r.path, 200)),
      imported_by_total: ins.rows[0]?.total ?? 0,
      imported_by: ins.rows.map((r) => clean(r.path, 200)),
      often_changed_with: co.rows.map((r) => ({ path: clean(r.path, 200), commits: r.count })),
      next: "Source code is not returned by this server. Use search_code for snippets or read the file in your own checkout.",
    },
    ["symbols", "imported_by", "imports", "often_changed_with"],
  );
}

// ---------------------------------------------------------------------------------------------------------------
export async function searchCode(
  { db, repo, fetchImpl = fetch }: Ctx,
  a: { query: string; mode: "hybrid" | "keyword" | "vector"; limit: number; path_prefix?: string; language?: string },
) {
  let hits: any[] | null = null;
  let how: string = a.mode;
  const warnings: string[] = [];
  try {
    const res = await fetchImpl(`${config.searchUrl}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // repo_id comes from resolveRepo (authorised), never from the caller
      body: JSON.stringify({ repo_id: repo.id, query: a.query, mode: a.mode, limit: a.limit, path_prefix: a.path_prefix, language: a.language }),
      signal: AbortSignal.timeout(config.toolTimeoutMs),
    });
    if (res.ok) {
      const body: any = await res.json();
      hits = body.hits ?? [];
      warnings.push(...(body.warnings ?? []).map((w: string) => clean(w, 160)));
    }
  } catch {
    /* service down: fall through to keyword search in SQL */
  }
  if (hits === null) {
    how = "keyword (fallback: search service unavailable)";
    const tsq = orQuery(a.query);
    const r = tsq ? await db.query(
      `SELECT path, language, kind, symbol, start_line, end_line, content,
              ts_rank_cd(tsv, to_tsquery('simple', $2)) AS score
       FROM chunks WHERE repo_id = $1 AND strategy = 'ast' AND tsv @@ to_tsquery('simple', $2)
         AND ($4::text IS NULL OR path LIKE $4 || '%') AND ($5::text IS NULL OR language = $5)
       ORDER BY score DESC, path, start_line LIMIT $3`,
      [repo.id, tsq, a.limit, a.path_prefix ? like(a.path_prefix) : null, a.language ?? null],
    ) : { rows: [] };
    hits = r.rows;
  }
  const items = hits.slice(0, a.limit).map((h) => ({
    path: clean(h.path, 200),
    lines: [h.start_line, h.end_line],
    symbol: h.symbol ? clean(h.symbol, 120) : undefined,
    kind: h.kind,
    score: Math.round(Number(h.score) * 1000) / 1000,
    snippet: clean(h.content, 700),
  }));
  return pack(
    { ...meta(repo), query: clean(a.query, 300), mode: how, ...(warnings.length ? { warnings } : {}) },
    items,
    0,
    false,
  );
}
