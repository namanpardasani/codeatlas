"""Where a change comes from: a commit in a local clone, a public GitHub pull request, or an uploaded diff.

Security:
  - PR URLs are parsed with a strict pattern (https://github.com/<owner>/<repo>/pull/<n>) and only ever turned into
    requests to the fixed host api.github.com: a user-supplied URL is never fetched as given (no SSRF).
  - Responses are size-capped and time-limited; the diff text is untrusted and goes to the strict parser in diff.py.
  - Revisions given to git are validated as hex SHAs and passed after --end-of-options.
  - A GitHub token, when configured, goes only in the Authorization header and is never logged.
"""
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..clone import git_env
from .changes import ChangeSet, analyze_change
from .diff import MAX_DIFF_BYTES, DiffError
from .source import GitSource, SourceError, resolve_rev

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
API = "https://api.github.com"
PR_URL = re.compile(r"^https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})/pull/([1-9][0-9]{0,8})/?$")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
HTTP_TIMEOUT_S = 20
MAX_JSON_BYTES = 2 * 1024 * 1024


class InputError(ValueError):
    pass


def _git(repo: Path, *args: str, timeout: int = 120) -> str:
    try:
        # bytes, then decode: text mode would turn \r\n into \n and a diff of a CRLF file would no longer match it
        out = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(repo), *args], env=git_env(),
                             capture_output=True, timeout=timeout, check=True).stdout
        return out.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        raise InputError(f"git {args[0]} failed: {e.stderr.decode(errors='replace').strip()[:200]}") from e
    except (subprocess.SubprocessError, OSError) as e:
        raise InputError(f"git {args[0]} failed: {type(e).__name__}") from e


def git_diff(repo: Path, base: str, head: str) -> str:
    """Unified diff base..head with rename detection; refuses huge outputs."""
    out = _git(repo, "diff", "--no-color", "--no-ext-diff", "-M", "--end-of-options", base, head)
    if len(out.encode("utf-8", errors="replace")) > MAX_DIFF_BYTES:
        raise InputError("the change is larger than the diff size limit")
    return out


@dataclass
class ResolvedChange:
    base: str                   # commit (or the empty tree) the change applies to
    head: str
    diff: str
    changes: ChangeSet


class _EmptyTree:
    def read_text(self, path):
        return None


def commit_change(repo: Path, rev: str, *, parser=None) -> ResolvedChange:
    """The change a commit made relative to its FIRST parent (a merge commit's own changes against the branch it
    was merged into). A root commit is compared with the empty tree."""
    if not (SHA.match(rev) or re.match(r"^[A-Za-z0-9_./~^-]{1,100}$", rev)) or rev.startswith("-"):
        raise InputError("invalid revision")
    try:
        head = resolve_rev(repo, rev)
    except SourceError as e:
        raise InputError(str(e)) from e
    parents = _git(repo, "rev-list", "--parents", "-n", "1", "--end-of-options", head).split()[1:]
    base = parents[0] if parents else EMPTY_TREE
    diff = git_diff(repo, base, head)
    old = GitSource(repo, base) if parents else _EmptyTree()
    new = GitSource(repo, head)
    return ResolvedChange(base, head, diff, analyze_change(diff, old.read_text, new.read_text, parser=parser))


def diff_change(diff_text: str, base_reader, *, parser=None) -> ChangeSet:
    """An uploaded diff against the analysed version: the new side is rebuilt by applying the patch."""
    try:
        return analyze_change(diff_text, base_reader, None, parser=parser)
    except DiffError as e:
        raise InputError(f"invalid diff: {e}") from e


# ---- GitHub pull requests -----------------------------------------------------------------------------------------

@dataclass
class PullRequest:
    owner: str
    repo: str
    number: int
    title: str
    author: str
    base_sha: str
    head_sha: str
    base_ref: str
    state: str
    changed_files: int


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = PR_URL.match(url.strip())
    if not m:
        raise InputError("expected a public GitHub pull request URL: https://github.com/<owner>/<repo>/pull/<number>")
    owner, repo, num = m.group(1), m.group(2), int(m.group(3))
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo, num


def _get(path: str, accept: str, limit: int, opener=None) -> bytes:
    req = urllib.request.Request(API + path, headers={
        "Accept": accept, "User-Agent": "codeatlas-blast-radius", "X-GitHub-Api-Version": "2022-11-28"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=HTTP_TIMEOUT_S) as resp:
            data = resp.read(limit + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise InputError("pull request not found (private repositories are not supported)") from e
        if e.code in (403, 429):
            raise InputError("GitHub rate limit reached; try again later") from e
        if e.code == 406:
            raise InputError("GitHub refused to render this diff (too large)") from e
        raise InputError(f"GitHub API error {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise InputError("could not reach GitHub") from e
    if len(data) > limit:
        raise InputError("GitHub response is larger than allowed")
    return data


def fetch_pr(owner: str, repo: str, number: int, *, opener=None) -> PullRequest:
    raw = _get(f"/repos/{owner}/{repo}/pulls/{number}", "application/vnd.github+json", MAX_JSON_BYTES, opener)
    try:
        d = json.loads(raw)
        pr = PullRequest(owner, repo, number, str(d.get("title", ""))[:300], str((d.get("user") or {}).get("login", "")),
                         d["base"]["sha"], d["head"]["sha"], str(d["base"].get("ref", ""))[:200], str(d.get("state", "")),
                         int(d.get("changed_files") or 0))
    except (ValueError, KeyError, TypeError) as e:
        raise InputError("unexpected response from GitHub") from e
    if not (SHA.match(pr.base_sha) and SHA.match(pr.head_sha)):
        raise InputError("unexpected commit ids from GitHub")
    return pr


def fetch_pr_diff(owner: str, repo: str, number: int, *, opener=None) -> str:
    """The PR's diff as GitHub renders it (merge-base...head). Used when there is no local clone to diff in."""
    return _get(f"/repos/{owner}/{repo}/pulls/{number}", "application/vnd.github.diff", MAX_DIFF_BYTES, opener).decode(
        "utf-8", errors="replace")


def pr_change(repo_dir: Path, pr: PullRequest, *, remote: str = "origin", parser=None) -> ResolvedChange:
    """Fetch the PR head (refs/pull/<n>/head works for PRs from forks too) and its base into an existing clone, then
    diff merge-base..head, which is exactly what GitHub shows as the PR's changes."""
    ref = f"refs/codeatlas/pr/{pr.number}"
    _git(repo_dir, "fetch", "--no-tags", "--quiet", remote, f"+refs/pull/{pr.number}/head:{ref}", timeout=180)
    try:
        resolve_rev(repo_dir, pr.base_sha)
    except SourceError:
        _git(repo_dir, "fetch", "--no-tags", "--quiet", remote, pr.base_sha, timeout=180)
    head = resolve_rev(repo_dir, ref)
    if head != pr.head_sha:
        raise InputError("the pull request changed while it was being fetched; try again")
    base = _git(repo_dir, "merge-base", "--end-of-options", pr.base_sha, head).strip()
    if not SHA.match(base):
        raise InputError("no common ancestor between the pull request and its base")
    diff = git_diff(repo_dir, base, head)
    return ResolvedChange(base, head, diff, analyze_change(diff, GitSource(repo_dir, base).read_text,
                                                           GitSource(repo_dir, head).read_text, parser=parser))
