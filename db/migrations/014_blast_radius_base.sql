-- Blast Radius, Phase 0: symbol fingerprints and directional co-change rules.

-- sha1 (16 hex) of the symbol's code tokens without whitespace/comments/docstrings: equal = same code.
-- Lets a diff tell "moved but unchanged" and "comment-only edit" apart from real changes.
ALTER TABLE symbols ADD COLUMN body_hash TEXT NOT NULL DEFAULT '';

-- Association rules from git history: confidence = P(target changes | source changes), support = shared commits.
-- Directional (unlike file_cochange.coupling, which is symmetric): both A->B and B->A rows may exist with different
-- confidence. Each source keeps only its strongest rules (see analyzer/blast/cochange.py).
CREATE TABLE cochange_rules (
  repo_id        BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  source_file_id BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  target_file_id BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  support        INTEGER NOT NULL CHECK (support > 0),
  confidence     REAL NOT NULL CHECK (confidence > 0 AND confidence <= 1),
  PRIMARY KEY (repo_id, source_file_id, target_file_id)
);
-- impact propagation walks rules backwards too ("which files pull this one along"), so index the target side
CREATE INDEX cochange_rules_target_idx ON cochange_rules (repo_id, target_file_id);

ALTER TABLE analysis_jobs
  ADD COLUMN cochange_commits_used    INTEGER,
  ADD COLUMN cochange_commits_skipped INTEGER;
