import subprocess
from datetime import datetime, timezone

import pytest

from analyzer import config, gitstats

from gitutil import DAY, T0, commit, init


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    init(r)
    # head is T0; window is 90 days back from the newest commit
    commit(r, T0 - 200 * DAY, "alice", {"a.py": "1", "b.py": "1"})   # old, outside window
    commit(r, T0 - 95 * DAY, "alice", {"a.py": "2"})                  # just outside
    commit(r, T0 - 40 * DAY, "bob", {"a.py": "3", "b.py": "3"})      # inside, a+b together
    commit(r, T0, "alice", {"a.py": "4", "b.py": "4", "c.py": "1"})  # head
    return r


def test_churn_authors_last_modified_and_window(repo):
    s = gitstats.collect(repo, window_days=90)
    a, b, c = s.files["a.py"], s.files["b.py"], s.files["c.py"]
    assert (a.commits_window, a.commits_total, a.authors) == (2, 4, 2)
    assert (b.commits_window, b.commits_total) == (2, 3)
    assert (c.commits_window, c.authors) == (1, 1)
    assert a.last_modified == datetime.fromtimestamp(T0, tz=timezone.utc)
    assert s.commits_seen == 4 and not s.truncated and s.error is None


def test_cochange_pairs_need_two_shared_commits(repo):
    s = gitstats.collect(repo, window_days=90)
    assert [(c.file_a, c.file_b, c.count, c.coupling) for c in s.cochange] == [("a.py", "b.py", 2, 1.0)]


def test_only_tracked_files_are_reported(repo):
    s = gitstats.collect(repo, tracked={"a.py"}, window_days=90)
    assert set(s.files) == {"a.py"} and s.cochange == []


def test_huge_commits_are_ignored_for_cochange(tmp_path):
    r = tmp_path / "r"
    init(r)
    for i in range(2):
        commit(r, T0 - i * DAY, "a", {f"f{n}.py": str(i) for n in range(config.COCHANGE_MAX_FILES_PER_COMMIT + 1)})
    s = gitstats.collect(r, window_days=90)
    assert s.cochange == [] and s.files["f0.py"].commits_window == 2


def test_shallow_clone_boundary_commit_is_not_counted(tmp_path, repo):
    # the oldest commit of a shallow clone appears to "add every file"; it must be excluded
    dest = tmp_path / "shallow"
    subprocess.run(["git", "-c", "protocol.file.allow=always", "clone", "-q", "--depth=3",
                    f"file://{repo}", str(dest)], check=True, capture_output=True)
    s = gitstats.collect(dest, window_days=90)
    assert s.commits_seen == 2                       # depth 3 = 3 commits, boundary dropped
    assert s.files["a.py"].commits_total == 2        # NOT 3
    assert s.truncated is False                      # boundary commit is 95 days back: window fully covered


def test_truncated_when_depth_limit_cuts_inside_the_window(tmp_path, repo):
    dest = tmp_path / "shallow2"
    subprocess.run(["git", "-c", "protocol.file.allow=always", "clone", "-q", "--depth=2",
                    f"file://{repo}", str(dest)], check=True, capture_output=True)
    s = gitstats.collect(dest, window_days=90)
    assert s.commits_seen == 1 and s.truncated is True  # boundary is 40 days back; window needs 90


def test_depth_one_clone_yields_no_stats_not_wrong_stats(tmp_path, repo):
    dest = tmp_path / "d1"
    subprocess.run(["git", "-c", "protocol.file.allow=always", "clone", "-q", "--depth=1",
                    f"file://{repo}", str(dest)], check=True, capture_output=True)
    s = gitstats.collect(dest)
    assert s.commits_seen == 0 and s.files == {}


def test_not_a_git_repo_is_an_error_value_not_an_exception(tmp_path):
    s = gitstats.collect(tmp_path)
    assert s.error and s.files == {}
