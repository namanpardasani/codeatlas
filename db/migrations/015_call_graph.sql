-- Blast Radius, Phase 1: function-level call graph.

ALTER TABLE symbols ADD COLUMN bases JSONB NOT NULL DEFAULT '[]';           -- classes: base classes as written
ALTER TABLE imports_raw ADD COLUMN bindings JSONB NOT NULL DEFAULT '[]';    -- [[local, imported], ...]
ALTER TABLE files ADD COLUMN export_aliases JSONB NOT NULL DEFAULT '[]';    -- [[exported, local], ...] (JS/TS)

-- Raw call sites and type hints per file, exactly as parsed. Kept so an incremental analysis can rebuild the whole
-- repo's call graph (a changed file can change how OTHER files' calls resolve) without re-parsing unchanged files.
CREATE TABLE file_call_sites (
  file_id   BIGINT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  repo_id   BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  calls     JSONB NOT NULL,      -- [[callee, qualifier, line, kind], ...]
  var_types JSONB NOT NULL       -- [[name, type_name, line], ...]
);
CREATE INDEX file_call_sites_repo_idx ON file_call_sites (repo_id);

-- caller_symbol_id NULL = module-level code of caller_file_id. Confidence is never upgraded: weak stays weak.
CREATE TABLE call_edges (
  id               BIGSERIAL PRIMARY KEY,
  repo_id          BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  caller_file_id   BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  caller_symbol_id BIGINT REFERENCES symbols(id) ON DELETE CASCADE,
  callee_file_id   BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  callee_symbol_id BIGINT NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
  confidence       TEXT NOT NULL CHECK (confidence IN ('exact', 'probable', 'weak')),
  line             INTEGER NOT NULL,
  kind             TEXT NOT NULL CHECK (kind IN ('call', 'new', 'jsx')),
  via              TEXT NOT NULL
);
CREATE INDEX call_edges_callee_idx ON call_edges (repo_id, callee_symbol_id);   -- who calls X (impact propagation)
CREATE INDEX call_edges_caller_idx ON call_edges (repo_id, caller_symbol_id);   -- what X calls
CREATE INDEX call_edges_callee_file_idx ON call_edges (repo_id, callee_file_id);

CREATE TABLE unresolved_calls (
  id               BIGSERIAL PRIMARY KEY,
  repo_id          BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  file_id          BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  caller_symbol_id BIGINT REFERENCES symbols(id) ON DELETE CASCADE,
  callee           TEXT NOT NULL,
  qualifier        TEXT,
  line             INTEGER NOT NULL,
  reason           TEXT NOT NULL
);
CREATE INDEX unresolved_calls_file_idx ON unresolved_calls (repo_id, file_id);

ALTER TABLE analysis_jobs ADD COLUMN call_stats JSONB;   -- {exact, probable, weak, external, unresolved:<reason>}
