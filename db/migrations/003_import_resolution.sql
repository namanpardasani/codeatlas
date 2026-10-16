-- Result of resolving each raw import (Day 3). Internal edges feed the dependency graph;
-- external packages are listed separately and are never graph nodes.
ALTER TABLE imports_raw
  ADD COLUMN resolution TEXT CHECK (resolution IN ('internal','external','unresolved')),
  ADD COLUMN targets    JSONB NOT NULL DEFAULT '[]',   -- repo-relative paths (internal only)
  ADD COLUMN package    TEXT,                          -- external package name
  ADD COLUMN reason     TEXT;                          -- why unresolved / extra detail
CREATE INDEX imports_raw_repo_resolution_idx ON imports_raw (repo_id, resolution);
