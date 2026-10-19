-- Day 4: complexity, git history, duplication, hotspots.
ALTER TABLE symbols
  ADD COLUMN complexity   INTEGER,          -- cyclomatic (functions/methods only)
  ADD COLUMN max_nesting  INTEGER,
  ADD COLUMN param_count  INTEGER;

ALTER TABLE files
  ADD COLUMN code_lines        INTEGER,
  ADD COLUMN comment_lines     INTEGER,
  ADD COLUMN comment_ratio     REAL,
  ADD COLUMN total_complexity  INTEGER,
  ADD COLUMN max_complexity    INTEGER,
  ADD COLUMN max_nesting       INTEGER,
  ADD COLUMN function_count    INTEGER,
  ADD COLUMN longest_function  INTEGER,
  ADD COLUMN churn             INTEGER,      -- commits touching the file inside the window
  ADD COLUMN commits_total     INTEGER,      -- ...in all fetched history
  ADD COLUMN authors           INTEGER,
  ADD COLUMN last_modified     TIMESTAMPTZ,
  ADD COLUMN dup_lines         INTEGER,
  ADD COLUMN dup_ratio         REAL,
  ADD COLUMN has_test          BOOLEAN,
  ADD COLUMN test_file         TEXT,
  ADD COLUMN hotspot_score     REAL,         -- NULL until a scoring formula exists
  ADD COLUMN hotspot_reasons   JSONB NOT NULL DEFAULT '[]',
  ADD COLUMN hotspot_detail    JSONB;        -- {contributions, normalized}
CREATE INDEX files_repo_hotspot_idx ON files (repo_id, hotspot_score DESC NULLS LAST);

ALTER TABLE analysis_jobs
  ADD COLUMN history_commits     INTEGER,
  ADD COLUMN history_window_days INTEGER,
  ADD COLUMN history_truncated   BOOLEAN,
  ADD COLUMN hotspot_config      JSONB;

CREATE TABLE file_cochange (
  repo_id   BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  file_a_id BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  file_b_id BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  count     INTEGER NOT NULL,      -- commits in the window that touched both
  coupling  REAL NOT NULL,         -- count / min(commits of a, commits of b)
  PRIMARY KEY (repo_id, file_a_id, file_b_id)
);
CREATE INDEX file_cochange_b_idx ON file_cochange (repo_id, file_b_id);

CREATE TABLE duplicate_groups (
  repo_id         BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  idx             INTEGER NOT NULL,
  lines           INTEGER NOT NULL,
  tokens          INTEGER NOT NULL,
  total_locations INTEGER NOT NULL,
  PRIMARY KEY (repo_id, idx)
);
CREATE TABLE duplicate_blocks (
  repo_id    BIGINT NOT NULL,
  group_idx  INTEGER NOT NULL,
  file_id    BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  start_line INTEGER NOT NULL,
  end_line   INTEGER NOT NULL,
  FOREIGN KEY (repo_id, group_idx) REFERENCES duplicate_groups(repo_id, idx) ON DELETE CASCADE
);
CREATE INDEX duplicate_blocks_file_idx ON duplicate_blocks (file_id);
CREATE INDEX duplicate_blocks_group_idx ON duplicate_blocks (repo_id, group_idx);
