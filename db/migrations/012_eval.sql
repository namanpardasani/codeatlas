-- Day 9: evaluation harness. Every run is stored whole so a published number can be traced to the run that made it.
CREATE TABLE eval_runs (
  id           BIGSERIAL PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('retrieval', 'answers', 'judge', 'graph')),
  label        TEXT NOT NULL DEFAULT '',          -- e.g. 'baseline', 'after-fix-1'
  git_sha      TEXT,
  dataset_hash TEXT NOT NULL,                     -- sha256 of the questions/graph file used
  config       JSONB NOT NULL,                    -- variants, k values, models, seeds, thresholds
  summary      JSONB NOT NULL,                    -- the headline numbers
  items        JSONB NOT NULL,                    -- per-question detail (for failure analysis)
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX eval_runs_kind_idx ON eval_runs (kind, id DESC);

-- LLM-judge verdicts, keyed by everything that influences them, so re-running the judge is free and reproducible.
CREATE TABLE eval_judge_cache (
  cache_key      TEXT PRIMARY KEY,                -- sha256(rubric_version, judge_model, question, notes, answer, evidence)
  judge_model    TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  verdict        JSONB NOT NULL,
  tokens_in      INTEGER,
  tokens_out     INTEGER,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
