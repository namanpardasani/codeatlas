"""Apply db/migrations/*.sql once each, in order (works without psql / docker).

    uv run python -m analyzer.migrate
"""
from pathlib import Path

import psycopg

from . import config

MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"


def main() -> None:
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                print(f"skip    {f.name}")
                continue
            with conn.transaction():  # a failed migration leaves nothing half-applied
                conn.execute(f.read_text())
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
            print(f"applied {f.name}")


if __name__ == "__main__":
    main()
