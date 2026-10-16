CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
  id          BIGSERIAL PRIMARY KEY,
  email       TEXT NOT NULL UNIQUE,
  name        TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE repos (
  id               BIGSERIAL PRIMARY KEY,
  owner_id         BIGINT REFERENCES users(id) ON DELETE SET NULL,
  url              TEXT NOT NULL UNIQUE,
  full_name        TEXT NOT NULL,            -- "owner/name", lowercased
  default_branch   TEXT,
  last_commit_sha  TEXT,
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','analyzing','ready','failed')),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analysis_jobs (
  id           BIGSERIAL PRIMARY KEY,
  repo_id      BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  commit_sha   TEXT,                          -- known only after clone
  status       TEXT NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued','running','done','failed')),
  stage        TEXT NOT NULL DEFAULT 'queued',
  progress     INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  attempts     INTEGER NOT NULL DEFAULT 0,
  error        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at   TIMESTAMPTZ,
  finished_at  TIMESTAMPTZ
);
CREATE INDEX analysis_jobs_repo_idx ON analysis_jobs (repo_id, created_at DESC);
CREATE INDEX analysis_jobs_status_idx ON analysis_jobs (status);

CREATE TABLE files (
  id            BIGSERIAL PRIMARY KEY,
  repo_id       BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  path          TEXT NOT NULL,
  language      TEXT,
  size          INTEGER NOT NULL DEFAULT 0,
  lines         INTEGER NOT NULL DEFAULT 0,
  content_hash  TEXT NOT NULL,
  commit_sha    TEXT,
  is_test       BOOLEAN NOT NULL DEFAULT false,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (repo_id, path)
);
