-- Day 8: access control for the MCP server.
-- API keys are never stored: only the SHA-256 of the key (a key is 256 random bits, so a fast hash is enough).
CREATE TABLE api_keys (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  key_hash    TEXT NOT NULL UNIQUE,
  key_prefix  TEXT NOT NULL,            -- first characters, to recognise a key in listings
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at  TIMESTAMPTZ,
  revoked_at  TIMESTAMPTZ
);

-- A key sees the repos its user owns, plus public ones. Only public GitHub repos can be analysed today, so the
-- default is true; set it to false for a repo that must stay private to its owner.
ALTER TABLE repos ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT true;
