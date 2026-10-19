-- File-level dependency graph (Day 3). Nodes are code files; `files.module IS NOT NULL` marks a node.
ALTER TABLE files
  ADD COLUMN module    TEXT,              -- folder cluster
  ADD COLUMN fan_in    INTEGER,           -- how many files import this one
  ADD COLUMN fan_out   INTEGER,           -- how many files this one imports
  ADD COLUMN pagerank  DOUBLE PRECISION,  -- centrality (sums to 1 across the repo)
  ADD COLUMN cycle_idx INTEGER;           -- group in dependency_cycles; NULL = not in a cycle

CREATE TABLE dependencies (
  id           BIGSERIAL PRIMARY KEY,
  repo_id      BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  from_file_id BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,  -- the importer
  to_file_id   BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,  -- the imported file
  kinds        JSONB NOT NULL DEFAULT '[]',  -- import / require / dynamic / reexport / from
  UNIQUE (repo_id, from_file_id, to_file_id)
);
CREATE INDEX dependencies_repo_from_idx ON dependencies (repo_id, from_file_id);
CREATE INDEX dependencies_repo_to_idx   ON dependencies (repo_id, to_file_id);

CREATE TABLE dependency_cycles (
  repo_id   BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  cycle_idx INTEGER NOT NULL,
  size      INTEGER NOT NULL,
  file_ids  JSONB NOT NULL,
  PRIMARY KEY (repo_id, cycle_idx)
);

-- Aggregated folder-level edges (from_module = to_module rows count edges inside a module).
CREATE TABLE module_edges (
  repo_id     BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  from_module TEXT NOT NULL,
  to_module   TEXT NOT NULL,
  edge_count  INTEGER NOT NULL,
  PRIMARY KEY (repo_id, from_module, to_module)
);
