ALTER TABLE files
  ADD COLUMN parse_status TEXT CHECK (parse_status IN ('ok','partial','failed','skipped')),
  ADD COLUMN parse_error  TEXT,
  ADD COLUMN exports      JSONB NOT NULL DEFAULT '[]';

CREATE TABLE symbols (
  id                BIGSERIAL PRIMARY KEY,
  repo_id           BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  file_id           BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  idx               INTEGER NOT NULL,          -- deterministic order within the file
  name              TEXT NOT NULL,
  kind              TEXT NOT NULL CHECK (kind IN ('function','class','method','interface','type','enum')),
  start_line        INTEGER NOT NULL,
  end_line          INTEGER NOT NULL,
  params            JSONB NOT NULL DEFAULT '[]',
  parent_name       TEXT,                      -- enclosing class/function (not an FK: names, not rows)
  is_exported       BOOLEAN NOT NULL DEFAULT false,
  is_default_export BOOLEAN NOT NULL DEFAULT false,
  has_doc           BOOLEAN NOT NULL DEFAULT false,
  signature         TEXT NOT NULL DEFAULT '',
  UNIQUE (file_id, idx)                        -- also serves "symbols of a file" lookups
);
CREATE INDEX symbols_repo_name_idx ON symbols (repo_id, name);
CREATE INDEX symbols_repo_kind_idx ON symbols (repo_id, kind);

-- Imports exactly as written; resolution to target files happens later (dependencies table).
CREATE TABLE imports_raw (
  id           BIGSERIAL PRIMARY KEY,
  repo_id      BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  file_id      BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  idx          INTEGER NOT NULL,
  specifier    TEXT NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('import','require','dynamic','reexport','from')),
  names        JSONB NOT NULL DEFAULT '[]',
  level        INTEGER NOT NULL DEFAULT 0,     -- Python relative-import dots
  line         INTEGER NOT NULL,
  is_type_only BOOLEAN NOT NULL DEFAULT false,
  UNIQUE (file_id, idx)
);
CREATE INDEX imports_raw_repo_spec_idx ON imports_raw (repo_id, specifier);
