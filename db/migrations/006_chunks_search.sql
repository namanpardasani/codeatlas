-- Day 5: searchable index. vector(384) matches BAAI/bge-small-en-v1.5; a model with another
-- dimension needs a new migration (the `embed_model` column keeps vectors of different models apart).

-- Content-hash cache: identical text is embedded once, across files, strategies and re-runs.
CREATE TABLE embedding_cache (
  embed_hash TEXT NOT NULL,          -- sha256(header + "\n" + content)
  model      TEXT NOT NULL,
  embedding  vector(384) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (embed_hash, model)
);

CREATE TABLE chunks (
  id           BIGSERIAL PRIMARY KEY,
  repo_id      BIGINT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  file_id      BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  strategy     TEXT NOT NULL CHECK (strategy IN ('ast', 'fixed')),   -- fixed = Day 9 baseline
  idx          INTEGER NOT NULL,
  path         TEXT NOT NULL,
  language     TEXT,
  kind         TEXT NOT NULL,        -- function|method|class|interface|type|enum|module|group|section|window
  symbol       TEXT,                 -- qualified name, e.g. Request.prepare_body
  parent_name  TEXT,                 -- enclosing class
  start_line   INTEGER NOT NULL,
  end_line     INTEGER NOT NULL,
  header       TEXT NOT NULL,        -- "path :: Class.method (method)"
  content      TEXT NOT NULL,
  content_hash TEXT NOT NULL,        -- sha256(content)
  embed_hash   TEXT NOT NULL,        -- sha256(header + content): the embedding-cache key
  embed_model  TEXT,
  embedding    vector(384),          -- NULL until embedded (keyword search works meanwhile)
  tsv          tsvector NOT NULL,
  UNIQUE (file_id, strategy, idx)
);
CREATE INDEX chunks_repo_strategy_idx ON chunks (repo_id, strategy);
CREATE INDEX chunks_embed_hash_idx    ON chunks (embed_hash);

-- Vector index. HNSW: layered proximity graph; builds incrementally (no training step, unlike
-- IVFFlat), better recall at the same latency; costs more memory and build time.
--   m = 16              links per node  (more = better recall, more memory)
--   ef_construction = 64 candidate list while building (more = better graph, slower build)
-- Query-time recall/latency knob: SET hnsw.ef_search (default 40; we use 100).
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Keyword index over the 'simple' text-search config (no stemming / stop words: right for identifiers).
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

ALTER TABLE analysis_jobs
  ADD COLUMN chunks_total    INTEGER,
  ADD COLUMN chunks_embedded INTEGER,   -- newly embedded this run
  ADD COLUMN chunks_cached   INTEGER,   -- served from the content-hash cache
  ADD COLUMN embed_model     TEXT,
  ADD COLUMN index_partial   BOOLEAN;   -- some chunks have no vector (budget hit or model unavailable)
