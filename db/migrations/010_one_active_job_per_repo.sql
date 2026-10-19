-- At most one queued/running analysis per repo: two concurrent analyses of the same repo would interleave their
-- writes. (This index already existed in the dev database via an unversioned migration; this makes it part of the repo.
-- IF NOT EXISTS keeps it idempotent for databases that already have it.)
CREATE UNIQUE INDEX IF NOT EXISTS analysis_jobs_one_active_per_repo
  ON analysis_jobs (repo_id) WHERE status IN ('queued', 'running');
