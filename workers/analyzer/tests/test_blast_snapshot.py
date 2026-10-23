"""Phase 0 of Blast Radius: snapshots at any commit, symbol fingerprints, history, directional co-change."""
import os
from pathlib import Path

import pytest

from analyzer.blast.cochange import build_cochange
from analyzer.blast.history import Commit, canonicalize, read_history
from analyzer.blast.snapshot import InProcessParser, ParseCache, build_snapshot
from analyzer.blast.source import DirSource, GitSource, SourceError
from analyzer.parsing import parse_source

from gitutil import DAY, T0, commit, git, init

P = InProcessParser()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    init(r)
    # c1: a library and a user of it, plus files the inventory must skip
    commit(r, T0, "ann", {
        "pkg/__init__.py": "",
        "pkg/a.py": "def helper(x):\n    return x + 1\n",
        "pkg/b.py": "from .a import helper\n\ndef use():\n    return helper(1)\n",
        "poetry.lock": "lock",
        "node_modules/dep/index.js": "module.exports = 1\n",
    })
    # c2: change a only
    commit(r, T0 + DAY, "bob", {"pkg/a.py": "def helper(x):\n    return x + 2\n"})
    # c3: add c (imports b) and a JS pair
    commit(r, T0 + 2 * DAY, "ann", {
        "pkg/c.py": "from pkg.b import use\n\nuse()\n",
        "web/util.js": "export function twice(n) { return n * 2 }\n",
        "web/main.js": "import { twice } from './util.js'\nconsole.log(twice(2))\n",
    })
    os.symlink("pkg/a.py", r / "link.py")   # symlinks are never followed (working tree only, not committed)
    return r


def test_git_source_reads_any_commit_without_checkout(repo):
    first = GitSource(repo, "HEAD~2")
    assert sorted(first.entries()) == ["pkg/__init__.py", "pkg/a.py", "pkg/b.py"]   # lockfile + node_modules skipped
    files = {sf.record.path: sf.data for sf in first.files()}
    assert files["pkg/a.py"] == b"def helper(x):\n    return x + 1\n"
    assert GitSource(repo, "HEAD").read_text("pkg/a.py") == "def helper(x):\n    return x + 2\n"


def test_unknown_revision_is_an_error(repo):
    with pytest.raises(SourceError):
        GitSource(repo, "no-such-branch")
    with pytest.raises(SourceError):
        GitSource(repo, "--output=/tmp/x")   # option injection is not possible (--end-of-options)


def test_git_snapshot_equals_checkout_snapshot(repo):
    via_git = build_snapshot(GitSource(repo, "HEAD"), parser=P)
    via_dir = build_snapshot(DirSource(repo), parser=P)
    assert {p: r.content_hash for p, r in via_git.files.items()} == {p: r.content_hash for p, r in via_dir.files.items()}
    assert via_git.imports_of == via_dir.imports_of
    assert via_git.imports_of == {"pkg/b.py": ["pkg/a.py"], "pkg/c.py": ["pkg/b.py"], "web/main.js": ["web/util.js"]}
    assert via_git.importers_of["pkg/a.py"] == ["pkg/b.py"]
    assert via_git.sha and via_dir.sha is None


def test_parse_cache_reparses_only_changed_content(repo):
    cache = ParseCache()
    build_snapshot(GitSource(repo, "HEAD~2"), parser=P, cache=cache)
    assert (cache.hits, cache.misses) == (0, 3)
    build_snapshot(GitSource(repo, "HEAD~1"), parser=P, cache=cache)   # only pkg/a.py changed
    assert (cache.hits, cache.misses) == (2, 4)
    snap = build_snapshot(GitSource(repo, "HEAD"), parser=P, cache=cache)   # 3 new files, a.py same as HEAD~1
    assert (cache.hits, cache.misses) == (5, 7)
    assert snap.parsed["pkg/a.py"].symbols[0].name == "helper"


def test_history_up_to_a_revision_excludes_later_commits(repo):
    hist = read_history(repo, "HEAD~1")
    assert [c.email for c in hist] == ["bob@x.dev", "ann@x.dev"]           # newest first, HEAD not included
    assert hist[0].files == ["pkg/a.py"]
    assert hist[0].time == T0 + DAY
    assert len(read_history(repo, "HEAD", since=T0 + DAY)) == 2


# ---- body fingerprints -------------------------------------------------------------------------------------------

def _hashes(path, src):
    return {s.name: s.body_hash for s in parse_source(path, src.encode()).symbols}


def test_body_hash_ignores_layout_comments_and_docstrings():
    a = _hashes("a.py", 'def f(x):\n    """Doc."""\n    return x+1  # note\n')
    b = _hashes("b.py", "\n\n# moved here\ndef f(x):\n    return x + 1\n")
    assert a["f"] == b["f"]


def test_body_hash_changes_with_code():
    assert _hashes("a.py", "def f(x):\n    return x + 1\n")["f"] != _hashes("a.py", "def f(x):\n    return x + 2\n")["f"]
    assert _hashes("a.py", "def f(x):\n    return x\n")["f"] != _hashes("a.py", "def f(y):\n    return y\n")["f"]


def test_body_hash_js_ignores_optional_semicolons_and_comments():
    a = _hashes("a.ts", "export function g(a: number) {\n  // twice\n  return a * 2;\n}\n")
    b = _hashes("b.ts", "export function g(a: number) { return a*2 }\n")
    assert a["g"] == b["g"]


def test_method_hash_is_its_own_and_class_hash_covers_methods():
    one = _hashes("a.py", "class K:\n    def m(self):\n        return 1\n    def n(self):\n        return 2\n")
    two = _hashes("a.py", "class K:\n    def m(self):\n        return 1\n    def n(self):\n        return 3\n")
    assert one["m"] == two["m"] and one["n"] != two["n"] and one["K"] != two["K"]


# ---- co-change ---------------------------------------------------------------------------------------------------

def C(*files, sha="x"):
    return Commit(sha, 0, "a@x", list(files))


def test_cochange_confidence_is_directional():
    commits = [C("big.py", "helper.py"), C("big.py", "helper.py"), C("big.py"), C("big.py"), C("helper.py", "other.py"),
               C("helper.py", "other.py")]
    m = build_cochange(commits)
    # big: 4 commits, 2 with helper -> P(helper | big) = 0.5 ; helper: 4 commits, 2 with big -> 0.5
    assert m.confidence("big.py", "helper.py") == 0.5
    assert m.confidence("helper.py", "other.py") == 0.5
    assert m.confidence("other.py", "helper.py") == 1.0     # other always changes with helper, not the reverse
    assert m.partners("other.py")[0].support == 2


def test_cochange_noise_filters():
    huge = C(*[f"f{i}.py" for i in range(60)])
    m = build_cochange([huge, huge, C("a.py", "poetry.lock"), C("a.py", "poetry.lock"), C("a.py", "b.py")])
    assert m.commits_skipped_large == 2
    assert m.rules == {}                       # lockfile ignored; a+b share only one commit (below min_support)
    m2 = build_cochange([C("a.py", "b.py"), C("a.py", "b.py"), C("gone.py", "a.py"), C("gone.py", "a.py")],
                        tracked={"a.py", "b.py"})
    assert [r.target for r in m2.partners("a.py")] == ["b.py"]   # files that no longer exist are dropped


def test_cochange_top_k_and_min_confidence():
    commits = [C("hub.py", f"s{i}.py") for i in range(5) for _ in range(2)] + [C("hub.py") for _ in range(30)]
    m = build_cochange(commits, top_k=3)
    assert m.partners("hub.py") == []             # P(s_i | hub) = 2/40 = 0.05 < 0.1
    assert len(m.partners("s0.py")) == 1 and m.partners("s0.py")[0].confidence == 1.0
    m2 = build_cochange(commits, top_k=3, min_confidence=0.01)
    assert [r.target for r in m2.partners("hub.py")] == ["s0.py", "s1.py", "s2.py"]


def test_cochange_from_real_history(repo):
    m = build_cochange(read_history(repo, "HEAD"))
    assert m.commits_used == 3
    # lockfile and node_modules never count; a.py changed in c1 and c2, b.py only in c1
    assert set(m.file_commits) == {"pkg/__init__.py", "pkg/a.py", "pkg/b.py", "pkg/c.py", "web/util.js", "web/main.js"}
    assert m.file_commits["pkg/a.py"] == 2
    assert m.rules == {}       # every pair shares at most one commit: below min_support


def test_renames_are_followed_so_history_survives_a_move(tmp_path):
    r = tmp_path / "mv"
    init(r)
    body = "def f():\n    return 1\n" * 20          # long enough for git's rename detection
    for i in range(2):
        commit(r, T0 + i * DAY, "ann", {"old/a.py": body + f"# {i}\n", "old/b.py": f"x = {i}\n"})
    (r / "src").mkdir()                              # git mv needs the target directory
    git(r, "mv", "old/a.py", "src/a.py")
    git(r, "mv", "old/b.py", "src/b.py")
    commit(r, T0 + 3 * DAY, "ann", {})
    commit(r, T0 + 4 * DAY, "ann", {"src/a.py": body + "# 9\n", "src/b.py": "x = 9\n"})
    hist = read_history(r, "HEAD")
    assert ("old/a.py", "src/a.py") in hist[1].renames
    canon = canonicalize(hist)
    assert all(set(c.files) <= {"src/a.py", "src/b.py"} for c in canon)
    m = build_cochange(hist, tracked={"src/a.py", "src/b.py"})
    assert m.partners("src/a.py")[0].support == 4        # 2 commits before the move + the move + 1 after


def test_canonicalize_follows_rename_chains():
    hist = [Commit("3", 3, "a", ["c.py"]), Commit("2", 2, "a", ["c.py"], [("b.py", "c.py")]),
            Commit("1", 1, "a", ["b.py"], [("a.py", "b.py")]), Commit("0", 0, "a", ["a.py", "z.py"])]
    assert [c.files for c in canonicalize(hist)] == [["c.py"], ["c.py"], ["c.py"], ["c.py", "z.py"]]


def test_history_works_in_a_blobless_partial_clone(repo, tmp_path):
    """The hosted worker clones with --filter=blob:none and lazy fetching off: rename detection would need old file
    contents, so history falls back to plain paths instead of failing (which used to yield an empty co-change model)."""
    import subprocess
    git(repo, "config", "uploadpack.allowFilter", "true")
    dest = tmp_path / "partial"
    subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-local", f"file://{repo}", str(dest)], check=True,
                   capture_output=True)
    from analyzer.blast.history import is_partial_clone
    assert is_partial_clone(dest) and not is_partial_clone(repo)
    hist = read_history(dest, "HEAD")
    assert len(hist) == 3 and hist[1].files == ["pkg/a.py"]
