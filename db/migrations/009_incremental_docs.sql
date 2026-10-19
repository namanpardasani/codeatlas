-- Day 7: incremental re-analysis bookkeeping + generated documentation.

-- ---- incremental re-analysis ------------------------------------------------------------------------------
ALTER TABLE repos
  ADD COLUMN pipeline_version  INTEGER,        -- bump when parser/chunker semantics change => forces a full re-analysis
  ADD COLUMN docs_status       TEXT CHECK (docs_status IN ('running', 'ready', 'partial', 'failed')),
  ADD COLUMN docs_commit_sha   TEXT,
  ADD COLUMN docs_model        TEXT,
  ADD COLUMN docs_generated_at TIMESTAMPTZ;

ALTER TABLE analysis_jobs
  ADD COLUMN requested_mode TEXT NOT NULL DEFAULT 'auto' CHECK (requested_mode IN ('auto', 'full')),
  ADD COLUMN mode           TEXT CHECK (mode IN ('full', 'incremental')),   -- what actually ran
  ADD COLUMN files_total    INTEGER,
  ADD COLUMN files_added    INTEGER,
  ADD COLUMN files_modified INTEGER,
  ADD COLUMN files_deleted  INTEGER,
  ADD COLUMN files_renamed  INTEGER,
  ADD COLUMN files_reused   INTEGER,           -- unchanged files whose parse/chunks/contents were reused
  ADD COLUMN stage_timings  JSONB,             -- {"parsing": ms, ...}
  ADD COLUMN duration_ms    INTEGER,
  ADD COLUMN docs_llm_calls INTEGER,
  ADD COLUMN docs_cached    INTEGER,
  ADD COLUMN docs_extractive INTEGER;

-- Normalised token streams of every parsed file: duplicate detection needs ALL files' tokens, and unchanged files
-- are not re-parsed. Packed little-endian uint32 arrays (hashes and line numbers).
CREATE TABLE file_tokens (
  file_id BIGINT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  n       INTEGER NOT NULL,
  hashes  BYTEA NOT NULL,
  lines   BYTEA NOT NULL
);

-- ---- generated documentation ------------------------------------------------------------------------------
-- Content-addressed LLM summary cache: identical input + prompt version + model never calls the LLM twice
-- (also across repos and forks).
CREATE TABLE summary_cache (
  input_hash     TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  model          TEXT NOT NULL,
  summary        TEXT NOT NULL,
  tokens_in      INTEGER,
  tokens_out     INTEGER,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (input_hash, prompt_version, model)
);

-- The current summary of each documented thing in a repo.
CREATE TABLE doc_summaries (
  repo_id        BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  target_type    TEXT NOT NULL CHECK (target_type IN ('symbol', 'file', 'folder', 'repo')),
  target_ref     TEXT NOT NULL,                -- path | path::Qualified.symbol | folder path ('' = repo root) | ''
  input_hash     TEXT NOT NULL,                -- Merkle hash of everything this summary depends on
  summary        TEXT NOT NULL,
  source         TEXT NOT NULL CHECK (source IN ('llm', 'extractive')),
  model          TEXT,
  prompt_version TEXT,
  commit_sha     TEXT,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (repo_id, target_type, target_ref)
);

-- Facts computed from the code (entry points, how to run, language mix), no LLM involved.
CREATE TABLE repo_facts (
  repo_id    BIGINT PRIMARY KEY REFERENCES repos(id) ON DELETE CASCADE,
  facts      JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
