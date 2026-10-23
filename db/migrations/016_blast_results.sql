-- Blast Radius, Phase 6: stored results (API / UI / MCP / GitHub App) and GitHub App bookkeeping.

CREATE TABLE blast_results (
  id          BIGSERIAL PRIMARY KEY,
  public_id   TEXT NOT NULL UNIQUE,                 -- unguessable id used in URLs (share links, PR comment link)
  repo_id     BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  input_kind  TEXT NOT NULL CHECK (input_kind IN ('pr', 'commit', 'diff')),
  input_ref   TEXT NOT NULL,                        -- PR URL, commit SHA as given, or diff:<sha256 prefix>
  base_sha    TEXT,
  head_sha    TEXT,
  risk_score  INTEGER,
  risk_label  TEXT,
  source      TEXT NOT NULL DEFAULT 'api' CHECK (source IN ('api', 'github', 'replay', 'mcp')),
  result      JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX blast_results_repo_idx ON blast_results (repo_id, created_at DESC);
CREATE INDEX blast_results_lookup_idx ON blast_results (repo_id, input_kind, input_ref, created_at DESC);

-- Webhook deliveries already handled (GitHub retries; X-GitHub-Delivery is unique per delivery).
CREATE TABLE github_deliveries (
  delivery_id TEXT PRIMARY KEY,
  event       TEXT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One run per (PR, head commit): idempotent processing; the comment is edited, never re-posted.
CREATE TABLE github_pr_runs (
  id              BIGSERIAL PRIMARY KEY,
  installation_id BIGINT NOT NULL,
  repo_full_name  TEXT NOT NULL,
  pr_number       INTEGER NOT NULL,
  head_sha        TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'waiting_analysis', 'running', 'done', 'failed')),
  comment_id      BIGINT,
  check_run_id    BIGINT,
  blast_result_id BIGINT REFERENCES blast_results(id) ON DELETE SET NULL,
  error           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (repo_full_name, pr_number, head_sha)
);
CREATE INDEX github_pr_runs_pr_idx ON github_pr_runs (repo_full_name, pr_number, created_at DESC);
