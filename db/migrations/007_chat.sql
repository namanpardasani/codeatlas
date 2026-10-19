-- Day 6: chat sessions + history, LLM usage caps, and stored file text (for the code viewer / citations).
CREATE TABLE chat_sessions (
  id         BIGSERIAL PRIMARY KEY,
  repo_id    BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  client_key TEXT NOT NULL,                 -- hashed client id (later: user id)
  title      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX chat_sessions_repo_idx ON chat_sessions (repo_id, client_key, updated_at DESC);

CREATE TABLE chat_messages (
  id         BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content    TEXT NOT NULL,
  status     TEXT CHECK (status IN ('answered', 'partial', 'not_found', 'error')),
  citations  JSONB NOT NULL DEFAULT '[]',   -- verified: [{label, chunk_id, path, start_line, end_line, ...}]
  retrieval  JSONB,                         -- what was retrieved/used (labels, scores) - for debugging and eval
  model      TEXT,
  usage      JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX chat_messages_session_idx ON chat_messages (session_id, id);

-- Per-client daily LLM budget (requests + tokens), checked before every call.
CREATE TABLE llm_usage (
  day           DATE NOT NULL,
  client_key    TEXT NOT NULL,
  requests      INTEGER NOT NULL DEFAULT 0,
  input_tokens  INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, client_key)
);

-- Full text of indexable files: the code viewer and "open at lines" citations read from here.
CREATE TABLE file_contents (
  file_id BIGINT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  content TEXT NOT NULL
);
