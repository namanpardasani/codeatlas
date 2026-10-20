#!/usr/bin/env python3
"""Export pre-analysed repositories from one CodeAtlas database and import them into another (e.g. a free hosted Postgres),
so a read-only demo works without running the analysis worker there.

  export:  python scripts/demo_data.py export OUT_DIR owner/name [owner/name ...]    (uses DATABASE_URL)
  import:  python scripts/demo_data.py import OUT_DIR                                  (uses DATABASE_URL; run migrations first)

Only data derived from the chosen repos is copied: no users, sessions, chats, usage, eval runs or LLM caches. Ids are preserved
and the sequences are advanced. Import refuses to overwrite a repo that already exists.
"""
import gzip
import os
import sys
from pathlib import Path

import psycopg

# parent tables first (foreign keys). (table, SQL selecting the rows to export for :ids = array of repo ids)
TABLES = [
    ("repos", "SELECT * FROM repos WHERE id = ANY(%(ids)s)"),
    ("analysis_jobs", "SELECT * FROM analysis_jobs WHERE repo_id = ANY(%(ids)s) AND status = 'done'"),
    ("files", "SELECT * FROM files WHERE repo_id = ANY(%(ids)s)"),
    ("symbols", "SELECT * FROM symbols WHERE repo_id = ANY(%(ids)s)"),
    ("imports_raw", "SELECT * FROM imports_raw WHERE repo_id = ANY(%(ids)s)"),
    ("dependencies", "SELECT * FROM dependencies WHERE repo_id = ANY(%(ids)s)"),
    ("dependency_cycles", "SELECT * FROM dependency_cycles WHERE repo_id = ANY(%(ids)s)"),
    ("module_edges", "SELECT * FROM module_edges WHERE repo_id = ANY(%(ids)s)"),
    ("file_cochange", "SELECT * FROM file_cochange WHERE repo_id = ANY(%(ids)s)"),
    ("duplicate_groups", "SELECT * FROM duplicate_groups WHERE repo_id = ANY(%(ids)s)"),
    ("duplicate_blocks", "SELECT * FROM duplicate_blocks WHERE repo_id = ANY(%(ids)s)"),
    ("chunks", "SELECT * FROM chunks WHERE repo_id = ANY(%(ids)s)"),
    ("file_contents", "SELECT fc.* FROM file_contents fc JOIN files f ON f.id = fc.file_id WHERE f.repo_id = ANY(%(ids)s)"),
    ("file_tokens", "SELECT ft.* FROM file_tokens ft JOIN files f ON f.id = ft.file_id WHERE f.repo_id = ANY(%(ids)s)"),
    ("doc_summaries", "SELECT * FROM doc_summaries WHERE repo_id = ANY(%(ids)s)"),
    ("repo_facts", "SELECT * FROM repo_facts WHERE repo_id = ANY(%(ids)s)"),
]
SEQUENCED = ["repos", "analysis_jobs", "files", "symbols", "imports_raw", "dependencies", "chunks"]


def dsn() -> str:
    return os.environ.get("DATABASE_URL") or "postgres://codeatlas:change-me-locally@127.0.0.1:5433/codeatlas"


def export(out: Path, names: list[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(dsn()) as conn:
        rows = conn.execute("SELECT id, full_name FROM repos WHERE full_name = ANY(%s) AND status = 'ready'", ([n.lower() for n in names],)).fetchall()
        found = {n for _, n in rows}
        missing = [n for n in names if n.lower() not in found]
        if missing:
            sys.exit(f"not analysed (status ready) in this database: {', '.join(missing)}")
        ids = [r[0] for r in rows]
        for table, sql in TABLES:
            n = 0
            with gzip.open(out / f"{table}.copy.gz", "wb") as f, conn.cursor().copy(f"COPY ({sql}) TO STDOUT", {"ids": ids}) as copy:
                for chunk in copy:
                    f.write(bytes(chunk))
            n = conn.execute(f"SELECT count(*) FROM ({sql}) t", {"ids": ids}).fetchone()[0]
            print(f"{table:20s} {n:>8d} rows  {(out / (table + '.copy.gz')).stat().st_size / 1024:>9.0f} KB")
    (out / "repos.txt").write_text("\n".join(sorted(found)) + "\n")


def load(src: Path) -> None:
    with psycopg.connect(dsn(), autocommit=False) as conn:
        names = (src / "repos.txt").read_text().split()
        clash = conn.execute("SELECT full_name FROM repos WHERE full_name = ANY(%s)", (names,)).fetchall()
        if clash:
            sys.exit(f"already present, refusing to overwrite: {[c[0] for c in clash]}")
        for table, _ in TABLES:
            with gzip.open(src / f"{table}.copy.gz", "rb") as f, conn.cursor().copy(f"COPY {table} FROM STDIN") as copy:
                while data := f.read(1 << 20):
                    copy.write(data)
        for t in SEQUENCED:
            conn.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT coalesce(max(id), 1) FROM {t}))")
        conn.commit()
    print(f"imported {len(names)} repos: {', '.join(names)}")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "export":
        export(Path(sys.argv[2]), sys.argv[3:])
    elif len(sys.argv) == 3 and sys.argv[1] == "import":
        load(Path(sys.argv[2]))
    else:
        sys.exit(__doc__)
