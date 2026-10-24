/**
 * The worked example on the landing page. Every value is copied from a real stored Blast Radius result
 * (psf/requests, commit 6f66281a, result id yECW7xKs98g8FIhx); nothing here is invented or rounded up.
 * If the result is re-run with a newer engine, update these numbers from GET /api/blast/<id>.
 */
export const EXAMPLE = {
  repo: "psf/requests",
  resultId: "yECW7xKs98g8FIhx",
  commit: "6f66281a",
  changed: [
    { path: "src/requests/models.py", what: "body of PreparedRequest.prepare_body and 2 helpers", plus: 4, minus: 7 },
    { path: "src/requests/_types.py", what: "adds has_read()", plus: 5, minus: 0 },
    { path: "tests/test_requests.py", what: "adds a read-only proxy test", plus: 15, minus: 0 },
  ],
  hops: [
    { hop: 1, path: "src/requests/__init__.py", why: "changed together with models.py in 35% of its commits (6 shared)" },
    { hop: 1, path: "src/requests/compat.py", why: "changed together with models.py in 29% of its commits (5 shared)" },
    { hop: 2, path: "src/requests/sessions.py", why: "calls PreparedRequest.prepare() on line 541" },
  ],
  tests: "4 of 346 tests selected (1%) + 1 new",
  risk: { score: 57, label: "medium", top: ["changes a complex function (_encode_files, complexity 22)", "models.py changed 17 times in recent history", "touches a file in an import cycle"] },
  /** files beyond the change with any impact, and those with impact >= 0.1 (what the risk score counts) */
  reached: 31,
  inBlast: 8,
  ms: 1466,
} as const;

/** Headline evaluation numbers (docs/BLAST_RADIUS_EVAL.md). */
export const EVAL = {
  validated: { pairs: 23, checked: 70, mrr: 0.831, baseline: 0.67 },
  all: { pairs: 477, mrr: 0.757, baseline: 0.731 },
  beyond: { pairs: 48, recall10: 0.381, folder: 0.414 },
  tests: { median: 6, catch: 70 },
  riskAuc: { v1: 0.707, size: 0.738 },
} as const;
