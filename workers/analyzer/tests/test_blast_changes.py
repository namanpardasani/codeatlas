"""Phase 2 of Blast Radius: unified diff parsing, patch application, line -> symbol attribution, change classification,
and the commit / raw diff / pull request inputs. Most cases build two real commits and let `git diff` produce the
input, so the parser is tested on real git output rather than hand-written diffs."""
import json
import subprocess
from pathlib import Path

import pytest

from analyzer.blast.changes import analyze_change, categorize, touched_symbols
from analyzer.blast.diff import DiffError, apply_patch, parse_diff
from analyzer.blast.inputs import (InputError, PullRequest, commit_change, diff_change, fetch_pr, parse_pr_url,
                                   pr_change)
from analyzer.blast.snapshot import InProcessParser
from analyzer.blast.source import GitSource
from analyzer.parsing.types import Symbol
from gitutil import DAY, T0, commit, git, init

P = InProcessParser()


def two_commits(tmp_path: Path, before: dict[str, str], after: dict[str, str | None], moves=()) -> Path:
    """Commit `before`, then apply `after` (None = delete) and `moves` [(old, new)] as a second commit."""
    r = tmp_path / "r"
    init(r)
    commit(r, T0, "ann", before)
    for old, new in moves:
        (r / new).parent.mkdir(parents=True, exist_ok=True)
        git(r, "mv", old, new)
    for path, content in after.items():
        if content is None:
            git(r, "rm", "-q", path)
        else:
            p = r / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            git(r, "add", path)
    commit(r, T0 + DAY, "bob", {})
    return r


def changes(r: Path):
    res = commit_change(r, "HEAD", parser=P)
    return {(f.path, s.change, s.name) for f in res.changes.files for s in f.symbols}, res


BASE = """import os


def parse(text, strict=False):
    # split on commas
    parts = text.split(",")
    return parts


def render(items):
    return ", ".join(items)


class Store:
    limit = 10

    def get(self, key):
        return self.data[key]

    def put(self, key, value):
        self.data[key] = value
"""


# ---- diff parser -------------------------------------------------------------------------------------------------

def test_parse_diff_statuses_and_line_numbers(tmp_path):
    r = two_commits(tmp_path, {"a.py": "x = 1\ny = 2\nz = 3\n", "gone.py": "q = 1\n", "old.py": "k = 1\n" * 30,
                               "img.png": "\x89PNG\x00\x01", "run.sh": "echo hi\n"},
                    {"a.py": "x = 1\ny = 20\nz = 3\nw = 4\n", "gone.py": None, "new.py": "n = 1\n"},
                    moves=[("old.py", "pkg/renamed.py")])
    (r / "run.sh").chmod(0o755)
    (r / "img.png").write_bytes(b"\x89PNG\x00\x02")
    git(r, "add", "run.sh", "img.png")
    commit(r, T0 + 2 * DAY, "bob", {})
    text = subprocess.run(["git", "-C", str(r), "diff", "-M", "HEAD~2", "HEAD"], capture_output=True, text=True).stdout
    by = {f.path: f for f in parse_diff(text)}
    assert by["a.py"].status == "modified" and by["a.py"].deleted == {2} and by["a.py"].added == {2, 4}
    assert by["gone.py"].status == "deleted" and by["gone.py"].new_path is None
    assert by["new.py"].status == "added" and by["new.py"].old_path is None and by["new.py"].added == {1}
    assert by["pkg/renamed.py"].status == "renamed" and by["pkg/renamed.py"].old_path == "old.py"
    assert by["img.png"].status == "binary"
    assert by["run.sh"].status == "mode_only"


def test_parse_diff_quoted_paths_and_no_newline_marker():
    text = ('diff --git "a/sp ace/\\303\\251.py" "b/sp ace/\\303\\251.py"\n--- "a/sp ace/\\303\\251.py"\n'
            '+++ "b/sp ace/\\303\\251.py"\n@@ -1 +1 @@\n-x = 1\n\\ No newline at end of file\n+x = 2\n'
            '\\ No newline at end of file\n')
    [f] = parse_diff(text)
    assert f.path == "sp ace/é.py" and f.deleted == {1} and f.added == {1}
    assert apply_patch("x = 1", f) == "x = 2"


def test_plain_unified_diff_without_git_header():
    text = "--- a.py\t2026-01-01\n+++ a.py\t2026-01-02\n@@ -1,2 +1,2 @@\n a = 1\n-b = 2\n+b = 3\n"
    [f] = parse_diff(text)
    assert f.path == "a.py" and f.status == "modified" and apply_patch("a = 1\nb = 2\n", f) == "a = 1\nb = 3\n"


@pytest.mark.parametrize("bad", [
    "diff --git a/../etc/passwd b/../etc/passwd\n--- a/../etc/passwd\n+++ b/../etc/passwd\n@@ -1 +1 @@\n-a\n+b\n",
    "diff --git a//abs b//abs\n--- a//abs\n+++ b//abs\n@@ -1 +1 @@\n-a\n+b\n",
    "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n a\n-b\n",            # hunk shorter than its header
    "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ bogus @@\n",
])
def test_malformed_or_unsafe_diffs_are_rejected(bad):
    with pytest.raises(DiffError):
        parse_diff(bad)


def test_size_limit():
    with pytest.raises(DiffError):
        parse_diff("x" * (5 * 1024 * 1024 + 1))


def test_apply_patch_rejects_a_diff_made_against_another_version():
    [f] = parse_diff("--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n a = 1\n-b = 2\n+b = 3\n")
    with pytest.raises(DiffError):
        apply_patch("a = 1\nb = 999\n", f)


def test_apply_patch_reproduces_every_real_commit(tmp_path):
    """Property: for each commit, applying its own diff to the parent's file gives the child's file, byte for byte."""
    r = two_commits(tmp_path, {"m.py": BASE, "t.txt": "a\nb\nc"},
                    {"m.py": BASE.replace("strict=False", "strict=True").replace("    limit = 10\n", "") + "\n\ndef extra():\n    pass\n",
                     "t.txt": "a\nB\nc\nd"})
    text = subprocess.run(["git", "-C", str(r), "diff", "HEAD~1", "HEAD"], capture_output=True, text=True).stdout
    old, new = GitSource(r, "HEAD~1"), GitSource(r, "HEAD")
    for f in parse_diff(text):
        assert apply_patch(old.read_text(f.old_path), f) == new.read_text(f.new_path), f.path


# ---- attribution -------------------------------------------------------------------------------------------------

def test_touched_symbols_innermost_and_outside():
    syms = [Symbol("K", "class", 1, 10), Symbol("m", "method", 3, 5, parent="K"), Symbol("f", "function", 12, 14)]
    hit, outside = touched_symbols(syms, {2, 4, 5, 6, 11, 12, 14, 20})
    assert hit == {0: [2, 6], 1: [4, 5], 2: [12, 14]}       # 2 and 6 are class-level lines, 4-5 belong to the method
    assert outside == [11, 20]


def test_touched_symbols_boundaries_are_inclusive():
    hit, outside = touched_symbols([Symbol("f", "function", 5, 7)], {4, 5, 7, 8})
    assert hit == {0: [5, 7]} and outside == [4, 8]


# ---- classification ----------------------------------------------------------------------------------------------

def test_body_signature_cosmetic_added_deleted(tmp_path):
    after = (BASE.replace("def parse(text, strict=False):", "def parse(text, strict=False, sep=','):")   # signature
                 .replace("    # split on commas\n", "    # split on the separator\n")                      # (comment)
                 .replace('return ", ".join(items)', 'return "; ".join(items)')                           # body
                 .replace("    def get(self, key):\n        return self.data[key]\n",
                          "    def get(self, key):\n        return self.data[key]  # fast path\n")         # cosmetic
                 .replace("    def put(self, key, value):\n        self.data[key] = value\n", "")          # deleted
             + "\n\ndef helper():\n    return 1\n")                                                         # added
    got, _ = changes(two_commits(tmp_path, {"m.py": BASE}, {"m.py": after}))
    assert got == {("m.py", "signature", "parse"), ("m.py", "body", "render"), ("m.py", "cosmetic", "Store.get"),
                   ("m.py", "deleted", "Store.put"), ("m.py", "added", "helper")}


def test_comment_and_whitespace_only_change_is_cosmetic(tmp_path):
    after = BASE.replace("    parts = text.split(\",\")", "    parts   =   text.split( \",\" )   # tidy")
    _, res = changes(two_commits(tmp_path, {"m.py": BASE}, {"m.py": after}))
    [f] = res.changes.files
    assert [s.change for s in f.symbols] == ["cosmetic"] and f.cosmetic_only and not f.module_changed


def test_move_inside_a_file_is_not_a_change(tmp_path):
    moved = BASE.replace("def render(items):\n    return \", \".join(items)\n\n\n", "") + \
        "\n\ndef render(items):\n    return \", \".join(items)\n"
    got, res = changes(two_commits(tmp_path, {"m.py": BASE}, {"m.py": moved}))
    assert got == {("m.py", "cosmetic", "render")} and res.changes.changed_symbols == []


def test_rename_is_detected(tmp_path):
    got, res = changes(two_commits(tmp_path, {"m.py": BASE}, {"m.py": BASE.replace("def render(", "def show(")}))
    assert got == {("m.py", "renamed", "show")}
    assert res.changes.files[0].symbols[0].note == "renamed from render"


def test_move_to_another_file(tmp_path):
    fn = "def render(items):\n    return \", \".join(items)\n"
    got, _ = changes(two_commits(tmp_path, {"m.py": BASE, "other.py": "X = 1\n"},
                                 {"m.py": BASE.replace(fn + "\n\n", ""), "other.py": "X = 1\n\n\n" + fn}))
    assert got == {("other.py", "moved", "render")}


def test_module_level_change_vs_module_level_comment(tmp_path):
    got, res = changes(two_commits(tmp_path, {"m.py": BASE}, {"m.py": BASE.replace("import os\n", "import os\nimport sys\n")}))
    assert got == set() and res.changes.files[0].module_changed
    _, res2 = changes(two_commits(tmp_path / "2", {"m.py": BASE}, {"m.py": "# header\n" + BASE}))
    assert not res2.changes.files[0].module_changed and res2.changes.files[0].cosmetic_only


def test_whole_file_added_deleted_and_renamed(tmp_path):
    got, res = changes(two_commits(tmp_path, {"gone.py": "def a():\n    pass\n", "keep.py": BASE},
                                   {"gone.py": None, "fresh.py": "def b():\n    return 2\n"},
                                   moves=[("keep.py", "pkg/keep.py")]))
    assert ("gone.py", "deleted", "a") in got and ("fresh.py", "added", "b") in got
    assert {s.change for f in res.changes.files if f.path == "pkg/keep.py" for s in f.symbols} == {"moved"}


def test_class_attribute_change_is_a_class_change_not_a_method_change(tmp_path):
    got, _ = changes(two_commits(tmp_path, {"m.py": BASE}, {"m.py": BASE.replace("limit = 10", "limit = 20")}))
    assert got == {("m.py", "body", "Store")}


def test_js_signature_and_export_change(tmp_path):
    before = "export function add(a, b) {\n  return a + b\n}\nfunction local() { return 1 }\n"
    after = "export function add(a, b, c = 0) {\n  return a + b + c\n}\nexport function local() { return 1 }\n"
    got, _ = changes(two_commits(tmp_path, {"m.js": before}, {"m.js": after}))
    assert got == {("m.js", "signature", "add"), ("m.js", "signature", "local")}   # newly exported = API change


def test_file_categories():
    assert [categorize(p) for p in ("src/a.py", "tests/test_a.py", "conftest.py", "package.json", "README.md",
                                    "config/app.yaml", "poetry.lock", ".github/workflows/ci.yml", "logo.png",
                                    "vite.config.ts", "requirements-dev.txt", "jest.setup.js")] == [
        "code", "test", "test_setup", "build", "docs", "config", "lockfile", "build", "other", "build", "build",
        "test_setup"]


# ---- inputs ------------------------------------------------------------------------------------------------------

def test_root_commit_and_merge_commit(tmp_path):
    r = tmp_path / "r"
    init(r)
    commit(r, T0, "ann", {"a.py": "def f():\n    return 1\n"})
    res = commit_change(r, "HEAD", parser=P)
    assert {(s.change, s.name) for s in res.changes.changed_symbols} == {("added", "f")}
    git(r, "checkout", "-q", "-b", "feat")
    commit(r, T0 + DAY, "bob", {"b.py": "def g():\n    return 2\n"})
    git(r, "checkout", "-q", "main")
    commit(r, T0 + 2 * DAY, "ann", {"a.py": "def f():\n    return 10\n"})
    git(r, "-c", "user.name=x", "-c", "user.email=x@x", "merge", "-q", "--no-ff", "-m", "m", "feat")
    merged = commit_change(r, "HEAD", parser=P)      # against the first parent: only what the branch brought in
    assert {(s.change, s.name) for s in merged.changes.changed_symbols} == {("added", "g")}


def test_commit_input_rejects_option_like_revisions(tmp_path):
    r = two_commits(tmp_path, {"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
    for bad in ("--output=/tmp/x", "-p", "a b", "HEAD;rm"):
        with pytest.raises(InputError):
            commit_change(r, bad, parser=P)


def test_raw_diff_applies_to_the_analysed_version(tmp_path):
    r = two_commits(tmp_path, {"m.py": BASE}, {"m.py": BASE.replace("return parts", "return [p.strip() for p in parts]")})
    text = subprocess.run(["git", "-C", str(r), "diff", "HEAD~1", "HEAD"], capture_output=True, text=True).stdout
    base = GitSource(r, "HEAD~1")
    cs = diff_change(text, base.read_text, parser=P)
    assert [(s.change, s.name) for s in cs.changed_symbols] == [("body", "parse")]
    stale = diff_change(text, lambda p: BASE.replace("parts = text", "pieces = text"), parser=P)
    assert stale.files[0].error and "does not apply" in stale.files[0].error and stale.changed_symbols == []


@pytest.mark.parametrize("url", ["https://github.com/psf/requests/pull/7505", "https://github.com/a-b/c.d_e/pull/1/"])
def test_pr_url_accepts_public_github_prs(url):
    owner, repo, n = parse_pr_url(url)
    assert owner and repo and n >= 1


@pytest.mark.parametrize("url", [
    "http://github.com/psf/requests/pull/1", "https://github.com.evil.com/a/b/pull/1",
    "https://github.com@evil.com/a/b/pull/1", "https://api.github.com/repos/a/b/pulls/1",
    "https://github.com/a/b/pull/1?x=../../", "https://github.com/a/b/pull/0", "https://github.com/a/b/issues/1",
    "https://github.com/../b/pull/1", "file:///etc/passwd", "https://169.254.169.254/a/b/pull/1",
])
def test_pr_url_rejects_everything_else(url):
    with pytest.raises(InputError):
        parse_pr_url(url)


class FakeResp:
    def __init__(self, body: bytes):
        self.body = body

    def read(self, n=-1):
        return self.body[:n] if n >= 0 else self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_pr_only_talks_to_the_github_api(monkeypatch):
    seen = []
    payload = {"title": "Fix", "user": {"login": "dev"}, "state": "open", "changed_files": 2,
               "base": {"sha": "a" * 40, "ref": "main"}, "head": {"sha": "b" * 40}}

    def opener(req, timeout):
        seen.append((req.full_url, dict(req.header_items())))
        return FakeResp(json.dumps(payload).encode())
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret")
    pr = fetch_pr("psf", "requests", 7, opener=opener)
    assert (pr.base_sha, pr.head_sha, pr.author, pr.changed_files) == ("a" * 40, "b" * 40, "dev", 2)
    assert seen[0][0] == "https://api.github.com/repos/psf/requests/pulls/7"
    assert seen[0][1]["Authorization"] == "Bearer ghs_secret"


def test_fetch_pr_rejects_odd_responses():
    bad = {"base": {"sha": "not-a-sha"}, "head": {"sha": "b" * 40}}
    with pytest.raises(InputError):
        fetch_pr("a", "b", 1, opener=lambda req, timeout: FakeResp(json.dumps(bad).encode()))
    with pytest.raises(InputError):
        fetch_pr("a", "b", 1, opener=lambda req, timeout: FakeResp(b"x" * (3 * 1024 * 1024)))


def test_pr_change_diffs_merge_base_to_head(tmp_path):
    """A local 'origin' with refs/pull/1/head, like GitHub: the PR branched off before main moved on."""
    origin = tmp_path / "origin"
    init(origin)
    commit(origin, T0, "ann", {"m.py": BASE})
    git(origin, "checkout", "-q", "-b", "pr")
    commit(origin, T0 + DAY, "bob", {"m.py": BASE.replace("return parts", "return list(parts)")})
    head = subprocess.run(["git", "-C", str(origin), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    git(origin, "update-ref", "refs/pull/1/head", head)
    git(origin, "checkout", "-q", "main")
    commit(origin, T0 + 2 * DAY, "ann", {"other.py": "def unrelated():\n    pass\n"})   # main moved on
    base_tip = subprocess.run(["git", "-C", str(origin), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", f"file://{origin}", str(clone)], check=True, capture_output=True)
    pr = PullRequest("o", "r", 1, "t", "bob", base_tip, head, "main", "open", 1)
    res = pr_change(clone, pr, parser=P)
    assert [(f.path, s.change, s.name) for f in res.changes.files for s in f.symbols] == [("m.py", "body", "parse")]
    # main's later commit (other.py) is not part of the PR's changes


def test_apply_patch_to_an_added_file_has_no_phantom_line():
    [f] = parse_diff("diff --git a/n.md b/n.md\nnew file mode 100644\n--- /dev/null\n+++ b/n.md\n@@ -0,0 +1,2 @@\n+a\n+\n")
    assert apply_patch("", f) == "a\n\n"


def test_crlf_files_survive_git_and_patching(tmp_path):
    """git in text mode turns \\r\\n into \\n; the diff must be read as bytes or it stops matching a CRLF file."""
    r = tmp_path / "r"
    init(r)
    (r / "w.py").write_bytes(b"def f():\r\n    return 1\r\n")
    git(r, "add", "w.py")
    commit(r, T0, "ann", {})
    (r / "w.py").write_bytes(b"def f():\r\n    return 2\r\n")
    git(r, "add", "w.py")
    commit(r, T0 + DAY, "ann", {})
    res = commit_change(r, "HEAD", parser=P)
    assert [(s.change, s.name) for s in res.changes.changed_symbols] == [("body", "f")]
    [f] = parse_diff(res.diff)
    assert apply_patch(GitSource(r, "HEAD~1").read_text("w.py"), f) == GitSource(r, "HEAD").read_text("w.py")
