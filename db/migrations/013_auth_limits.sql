-- Day 10: GitHub login, sessions, per-user analysis quotas.
-- No GitHub access token is ever stored: it is used once to read the public profile and discarded.
ALTER TABLE users
  ADD COLUMN github_id  BIGINT UNIQUE,
  ADD COLUMN login      TEXT,
  ADD COLUMN avatar_url TEXT;

-- Opaque session tokens: only the SHA-256 is stored (a database leak cannot be replayed as a login).
CREATE TABLE sessions (
  id         BIGSERIAL PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX sessions_user_idx ON sessions (user_id);

-- Who asked for an analysis: a user, or (anonymous, only when login is not required) a salted hash of the client IP.
ALTER TABLE analysis_jobs
  ADD COLUMN requested_by     BIGINT REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN requested_by_key TEXT;
CREATE INDEX analysis_jobs_requester_idx ON analysis_jobs (requested_by, created_at);
CREATE INDEX analysis_jobs_requester_key_idx ON analysis_jobs (requested_by_key, created_at);
