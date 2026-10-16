"""Integration test against the dev Postgres (skipped when it is not reachable)."""
import pytest

from analyzer import db
from analyzer.inventory import FileRecord
from analyzer.parsing import parse_source

try:
    conn = db.connect()
except Exception:  # noqa: BLE001
    conn = None

pytestmark = pytest.mark.skipif(conn is None, reason="Postgres not available")


@pytest.fixture
def repo_id():
    rid = conn.execute(
        "INSERT INTO repos (url, full_name) VALUES ('https://github.com/test/idem', 'test/idem') "
        "ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id").fetchone()[0]
    yield rid
    conn.execute("DELETE FROM repos WHERE id = %s", (rid,))


def counts(rid):
    return tuple(conn.execute(f"SELECT count(*) FROM {t} WHERE repo_id = %s", (rid,)).fetchone()[0]
                 for t in ("files", "symbols", "imports_raw"))


def test_rerun_does_not_duplicate_rows(repo_id):
    src = b"import a from './a';\nexport function f(x) {}\nexport class C { m() {} }\n"
    rec = FileRecord("a.ts", "typescript", len(src), 3, "h", False)
    for _ in range(3):
        ids = db.save_files(conn, repo_id, "sha", [rec])
        db.save_parse_results(conn, repo_id, {ids["a.ts"]: parse_source("a.ts", src)})
    assert counts(repo_id) == (1, 3, 1)
    row = conn.execute("SELECT parse_status, exports FROM files WHERE repo_id=%s", (repo_id,)).fetchone()
    assert row[0] == "ok" and set(row[1]) == {"f", "C"}


def test_vanished_files_are_removed_with_their_symbols(repo_id):
    src = b"export function f() {}\n"
    recs = [FileRecord(p, "typescript", 10, 1, "h", False) for p in ("a.ts", "b.ts")]
    ids = db.save_files(conn, repo_id, "s1", recs)
    db.save_parse_results(conn, repo_id, {i: parse_source("x.ts", src) for i in ids.values()})
    assert counts(repo_id) == (2, 2, 0)
    ids = db.save_files(conn, repo_id, "s2", recs[:1])
    db.save_parse_results(conn, repo_id, {i: parse_source("x.ts", src) for i in ids.values()})
    assert counts(repo_id) == (1, 1, 0)
