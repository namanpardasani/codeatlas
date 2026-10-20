import { pool } from "./db.js";

const STOP = new Set("the and are for how what where which does with from that this into when who why can you use used not has have was were".split(" "));

/** OR-query from plain identifier-like words only, so nothing user-typed can reach tsquery syntax. */
export const orQuery = (q: string) =>
  [...new Set((q.toLowerCase().match(/[a-z_][a-z0-9_]{2,}/g) ?? []).filter((w) => !STOP.has(w)))].slice(0, 8).join(" | ");

const like = (s: string) => s.replace(/[\\%_]/g, (c) => `\\${c}`);

/**
 * Degraded search used when the Python search service is not running (for example the free read-only demo): Postgres
 * full-text search over the stored chunks. Same response shape as the service, labelled so the UI can say so.
 */
export async function keywordSearch(
  repoId: number,
  a: { query: string; limit: number; chunking?: string; language?: string; path_prefix?: string; kind?: string },
) {
  const tsq = orQuery(a.query);
  const rows = tsq
    ? (
        await pool.query(
          `SELECT id, path, language, kind, symbol, parent_name, start_line, end_line, header, content,
                  ts_rank_cd(tsv, to_tsquery('simple', $2)) AS score
           FROM chunks
           WHERE repo_id = $1 AND strategy = $3 AND tsv @@ to_tsquery('simple', $2)
             AND ($4::text IS NULL OR language = $4) AND ($5::text IS NULL OR path LIKE $5 || '%') AND ($6::text IS NULL OR kind = $6)
           ORDER BY score DESC, path, start_line LIMIT $7`,
          [repoId, tsq, a.chunking ?? "ast", a.language ?? null, a.path_prefix ? like(a.path_prefix) : null, a.kind ?? null, a.limit],
        )
      ).rows
    : [];
  return {
    hits: rows.map((r) => ({
      chunk_id: Number(r.id), path: r.path, language: r.language, kind: r.kind, symbol: r.symbol, parent: r.parent_name,
      start_line: r.start_line, end_line: r.end_line, header: r.header, content: r.content, score: Number(r.score),
      vector_rank: null, vector_similarity: null, keyword_rank: null, keyword_score: Number(r.score),
    })),
    terms: tsq ? tsq.split(" | ") : [],
    mode: "keyword",
    chunking: a.chunking ?? "ast",
    warnings: ["The semantic search service is not available here: showing keyword results only."],
    timings_ms: {},
  };
}
