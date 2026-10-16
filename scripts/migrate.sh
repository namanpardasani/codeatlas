#!/usr/bin/env bash
# Apply db/migrations/*.sql in order, once each. Safe to re-run.
# Uses DATABASE_URL with local psql if set, else the compose postgres container.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -n "${DATABASE_URL:-}" ]; then
  run() { psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -qtA "$@"; }
else
  run() { docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -qtA' "$@"; }
fi

echo "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now());" | run

for f in db/migrations/*.sql; do
  name=$(basename "$f")
  done_already=$(echo "SELECT 1 FROM schema_migrations WHERE name='$name';" | run)
  if [ -n "$done_already" ]; then echo "skip   $name"; continue; fi
  { echo "BEGIN;"; cat "$f"; echo "INSERT INTO schema_migrations(name) VALUES ('$name');"; echo "COMMIT;"; } | run
  echo "applied $name"
done
