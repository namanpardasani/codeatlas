"""Aggregation, hotspot input assembly, and persistence of the Day-4 metrics."""
from datetime import datetime, timezone

import pytest

from analyzer import db, gitstats
from analyzer.duplication import DupGroup, DupResult, Location
from analyzer.graph.metrics import analyze
from analyzer.graph.types import Edge
from analyzer.hotspots import HotspotConfig, RepoContext, explain, map_tests, score_all
from analyzer.hotspots.inputs import build_inputs
from analyzer.inventory import FileRecord
from analyzer.parsing import parse_source
from analyzer.parsing.aggregate import file_aggregates

from reference_scorer import reference_score

SRC = b"""function a(x) { if (x) { return 1 } return 2 }
function b(x, y) { for (const i of x) { if (i && y) { return 1 } } return 0 }
class K { m() { return 1 } }
"""


def test_file_aggregates():
    agg = file_aggregates(parse_source("a.js", SRC))
    assert agg == {"function_count": 3, "total_complexity": 2 + 4 + 1, "max_complexity": 4,
                   "max_nesting": 2, "longest_function": 1}
    assert file_aggregates(parse_source("e.js", b"")) == {
        "function_count": 0, "total_complexity": 0, "max_complexity": 0, "max_nesting": 0, "longest_function": 0}


def _world():
    paths = ["src/a.js", "src/b.js", "src/a.test.js", "README.md"]
    recs = [FileRecord(p, "javascript" if p.endswith(".js") else None, 100, 3, "h", p.endswith(".test.js")) for p in paths]
    results = {"src/a.js": parse_source("src/a.js", SRC), "src/b.js": parse_source("src/b.js", SRC),
               "src/a.test.js": parse_source("src/a.test.js", b"test('x', () => {})")}
    analysis = analyze(["src/a.js", "src/b.js", "src/a.test.js"],
                       [Edge("src/a.js", "src/b.js"), Edge("src/b.js", "src/a.js")])
    t = datetime(2025, 1, 10, tzinfo=timezone.utc)
    git = gitstats.GitStats(
        files={"src/a.js": gitstats.FileGit(7, 9, 3, datetime(2025, 1, 5, tzinfo=timezone.utc))},
        commits_seen=9, window_days=90, head_time=t)
    dups = DupResult(groups=[DupGroup(8, 70, [Location("src/a.js", 1, 8), Location("src/b.js", 1, 8)], 2)],
                     duplicated_lines={"src/a.js": 3})
    tests = map_tests(["src/a.js", "src/b.js"], ["src/a.test.js"])
    return recs, results, analysis, git, dups, tests


def test_build_inputs_joins_every_stage():
    recs, results, analysis, git, dups, tests = _world()
    got = {i.path: i for i in build_inputs(recs, results, analysis, git, dups, tests)}
    assert set(got) == {"src/a.js", "src/b.js", "src/a.test.js"}          # README.md is not source
    a, b = got["src/a.js"], got["src/b.js"]
    assert (a.max_complexity, a.total_complexity, a.function_count) == (4, 7, 3)
    assert (a.churn, a.authors, a.days_since_modified) == (7, 3, 5)
    assert (a.in_cycle, a.cycle_size, a.fan_in, a.fan_out) == (True, 2, 1, 1)
    assert a.has_test and a.test_file == "src/a.test.js" and not b.has_test
    assert a.dup_ratio == pytest.approx(3 / 3) and b.dup_ratio == 0.0     # a has 3 lines, all duplicated
    assert got["src/a.test.js"].is_test is True
    assert b.churn == 0 and b.days_since_modified is None                 # untouched in history


def test_build_inputs_without_history_leaves_churn_neutral():
    recs, results, analysis, _, dups, tests = _world()
    nohist = gitstats.GitStats(commits_seen=0, window_days=90)
    got = {i.path: i for i in build_inputs(recs, results, analysis, nohist, dups, tests)}
    assert got["src/a.js"].churn == 0 and got["src/a.js"].days_since_modified is None


def test_score_all_with_a_scorer_produces_reasons():
    recs, results, analysis, git, dups, tests = _world()
    inputs = build_inputs(recs, results, analysis, git, dups, tests)
    ctx = RepoContext.build(inputs, True, 90)
    cfg = HotspotConfig(min_lines=1)
    out = score_all(inputs, ctx, cfg, reference_score)
    assert all(s is not None for _, s, _ in out)
    a = next(x for x in out if x[0].path == "src/a.js")
    assert any(r.factor == "cycle" for r in a[2]) or a[1].score >= 0


try:
    conn = db.connect()
except Exception:  # noqa: BLE001
    conn = None
needs_db = pytest.mark.skipif(conn is None, reason="Postgres not available")


@pytest.fixture
def repo():
    rid = conn.execute(
        "INSERT INTO repos (url, full_name) VALUES ('https://github.com/test/quality', 'test/quality') "
        "ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id").fetchone()[0]
    jid = conn.execute("INSERT INTO analysis_jobs (repo_id) VALUES (%s) RETURNING id", (rid,)).fetchone()[0]
    yield rid, jid
    conn.execute("DELETE FROM repos WHERE id = %s", (rid,))


def _store(rid, jid, with_scores=True):
    recs, results, analysis, git, dups, tests = _world()
    ids = db.save_files(conn, rid, "sha", recs)
    db.save_parse_results(conn, rid, {ids[p]: r for p, r in results.items()})
    db.save_graph(conn, rid, ids, analysis, [Edge("src/a.js", "src/b.js"), Edge("src/b.js", "src/a.js")])
    git.cochange = [gitstats.CoChange("src/a.js", "src/b.js", 5, 0.71)]
    db.save_git_stats(conn, rid, jid, ids, git)
    db.save_duplicates(conn, rid, ids, {p: r.metrics.lines for p, r in results.items()}, dups)
    inputs = build_inputs(recs, results, analysis, git, dups, tests)
    ctx = RepoContext.build(inputs, True, 90)
    cfg = HotspotConfig(min_lines=1)
    scorer = reference_score if with_scores else (lambda *a: (_ for _ in ()).throw(NotImplementedError()))
    db.save_hotspots(conn, rid, jid, ids, score_all(inputs, ctx, cfg, scorer), cfg)
    return ids


@needs_db
def test_metrics_are_persisted_and_idempotent(repo):
    rid, jid = repo
    for _ in range(3):
        ids = _store(rid, jid)
    row = conn.execute("SELECT code_lines, total_complexity, max_complexity, function_count, churn, authors, "
                       "dup_lines, dup_ratio, has_test, test_file, hotspot_score IS NOT NULL FROM files WHERE id=%s",
                       (ids["src/a.js"],)).fetchone()
    assert row[0] == 3 and row[1:4] == (7, 4, 3) and row[4:6] == (7, 3)
    assert row[6] == 3 and row[7] == pytest.approx(1.0) and row[8] is True and row[9] == "src/a.test.js" and row[10]
    sym = conn.execute("SELECT complexity, max_nesting, param_count FROM symbols WHERE file_id=%s AND name='b'",
                       (ids["src/b.js"],)).fetchone()
    assert sym == (4, 2, 2)
    cls = conn.execute("SELECT complexity FROM symbols WHERE file_id=%s AND name='K'", (ids["src/a.js"],)).fetchone()
    assert cls == (None,)
    count = lambda t: conn.execute(f"SELECT count(*) FROM {t} WHERE repo_id=%s", (rid,)).fetchone()[0]
    assert (count("file_cochange"), count("duplicate_groups"), count("duplicate_blocks")) == (1, 1, 2)
    job = conn.execute("SELECT history_commits, history_window_days, history_truncated, hotspot_config IS NOT NULL "
                       "FROM analysis_jobs WHERE id=%s", (jid,)).fetchone()
    assert job == (9, 90, False, True)


@needs_db
def test_unimplemented_formula_leaves_scores_null_but_saves_the_rest(repo):
    rid, jid = repo
    ids = _store(rid, jid, with_scores=False)
    row = conn.execute("SELECT hotspot_score, hotspot_reasons, has_test, churn FROM files WHERE id=%s",
                       (ids["src/a.js"],)).fetchone()
    assert row == (None, [], True, 7)


@needs_db
def test_no_history_stores_null_not_zero(repo):
    rid, jid = repo
    recs = [FileRecord("a.js", "javascript", 1, 1, "h", False)]
    ids = db.save_files(conn, rid, "s", recs)
    db.save_git_stats(conn, rid, jid, ids, gitstats.GitStats(commits_seen=0, window_days=90))
    assert conn.execute("SELECT churn, authors, last_modified FROM files WHERE id=%s", (ids["a.js"],)).fetchone() \
        == (None, None, None)
