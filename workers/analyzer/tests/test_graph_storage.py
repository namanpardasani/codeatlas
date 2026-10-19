"""Edge extraction (pure) + graph persistence (needs the dev Postgres; skipped otherwise)."""
import pytest

from analyzer import db
from analyzer.graph.edges import edges_from_resolutions
from analyzer.graph.metrics import analyze
from analyzer.graph.types import Edge
from analyzer.inventory import FileRecord
from analyzer.resolve.types import ImportResolution, Resolution


def res(frm, status, targets=(), kind="import"):
    return ImportResolution(frm, 0, kind, Resolution(status, list(targets)))


def test_only_internal_code_to_code_imports_become_edges():
    nodes = {"a.ts", "b.ts"}
    rs = [
        res("a.ts", "internal", ["b.ts"]),
        res("a.ts", "internal", ["style.css"]),      # asset, not a graph node
        res("a.ts", "external"),
        res("a.ts", "unresolved"),
        res("x.ts", "internal", ["b.ts"]),           # importer not a node
        res("a.ts", "internal", ["b.ts"], "dynamic"),
    ]
    edges = edges_from_resolutions(rs, nodes)
    assert edges == [Edge("a.ts", "b.ts", "import"), Edge("a.ts", "b.ts", "dynamic")]


try:
    conn = db.connect()
except Exception:  # noqa: BLE001
    conn = None


@pytest.fixture
def repo_id():
    rid = conn.execute(
        "INSERT INTO repos (url, full_name) VALUES ('https://github.com/test/graph', 'test/graph') "
        "ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id").fetchone()[0]
    yield rid
    conn.execute("DELETE FROM repos WHERE id = %s", (rid,))


@pytest.mark.skipif(conn is None, reason="Postgres not available")
def test_save_graph_is_idempotent_and_stores_everything(repo_id):
    paths = ["src/a.ts", "src/b.ts", "lib/u.ts", "README.md"]
    recs = [FileRecord(p, "typescript", 1, 1, "h", False) for p in paths]
    ids = db.save_files(conn, repo_id, "sha", recs)
    edges = [Edge("src/a.ts", "src/b.ts"), Edge("src/b.ts", "src/a.ts", "dynamic"),
             Edge("src/a.ts", "lib/u.ts"), Edge("src/a.ts", "lib/u.ts", "require")]
    analysis = analyze(["src/a.ts", "src/b.ts", "lib/u.ts"], edges)

    for _ in range(3):
        db.save_graph(conn, repo_id, ids, analysis, edges)

    count = lambda t: conn.execute(f"SELECT count(*) FROM {t} WHERE repo_id=%s", (repo_id,)).fetchone()[0]
    assert (count("dependencies"), count("dependency_cycles"), count("module_edges")) == (3, 1, 2)
    kinds = conn.execute("SELECT kinds FROM dependencies d JOIN files f ON f.id=d.to_file_id "
                         "WHERE d.repo_id=%s AND f.path='lib/u.ts'", (repo_id,)).fetchone()[0]
    assert kinds == ["import", "require"]
    row = conn.execute("SELECT module, fan_in, fan_out, cycle_idx FROM files WHERE id=%s",
                       (ids["src/a.ts"],)).fetchone()
    assert row == ("src", 1, 2, 0)
    readme = conn.execute("SELECT module, pagerank FROM files WHERE id=%s", (ids["README.md"],)).fetchone()
    assert readme == (None, None)  # non-graph files carry no metrics
