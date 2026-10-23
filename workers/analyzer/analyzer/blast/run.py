"""Run Blast Radius for an analysed repo from a PR URL, a commit SHA or a unified diff. Used by the internal service
(API + MCP) and safe for untrusted input:
  - the repo comes from the database (an analysed public GitHub repo), never from the request;
  - a PR URL must point at that same repo; only api.github.com is contacted (inputs.py);
  - SHAs are validated hex; diffs are size-capped and parsed strictly; a diff must apply to the analysed version;
  - parsing runs in the sandboxed child process; repo code is never executed;
  - clones are cached per repo under BLAST_CLONE_DIR (bounded history, hooks off, allowlisted URL), base models are
    cached in memory per (repo, base sha).
"""
import hashlib
import json
import logging
import re
import shutil
import subprocess
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..clone import clone, git_env
from .engine import BaseModel, BlastReport, analyze_commit, base_model, commit_author
from .history import read_history  # noqa: F401  (re-exported for tests)
from .impact import Params, apply_change_paths, propagate, seeds_from
from .inputs import InputError, ResolvedChange, diff_change, fetch_pr, parse_pr_url, pr_change
from .report import to_json
from .reviewers import suggest_reviewers
from .risk import Logistic, risk
from .snapshot import ParseCache
from .source import GitSource, SourceError
from .testsel import select_tests

log = logging.getLogger("analyzer.blast")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
PRODUCT = Params(tiered=True)

_lock = threading.Lock()                    # one analysis at a time per process: bounded CPU and memory
_bases: "OrderedDict[tuple[int, str], BaseModel]" = OrderedDict()
_caches: dict[int, ParseCache] = {}
MAX_BASES = 4
MAX_CLONES = 8          # disk bound for BLAST_CLONE_DIR: least recently used clones are deleted


@dataclass
class RepoRow:
    id: int
    url: str
    full_name: str
    sha: str | None


def _risk_model() -> Logistic | None:
    if not config.BLAST_RISK_MODEL:
        return None
    try:
        d = json.loads(Path(config.BLAST_RISK_MODEL).read_text())
        return Logistic(d["weights"], d["bias"], d["mean"], d["std"])
    except (OSError, ValueError, KeyError):
        log.warning("risk model %s unreadable; using v1 weights", config.BLAST_RISK_MODEL)
        return None


def _git(repo: Path, *args: str, timeout: int = 180) -> None:
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args], env=git_env(),
                   capture_output=True, timeout=timeout, check=True)


def ensure_clone(r: RepoRow) -> Path:
    root = Path(config.BLAST_CLONE_DIR)
    dest = root / f"repo-{r.id}"
    if not (dest / ".git").exists():
        shutil.rmtree(dest, ignore_errors=True)
        clone(r.url, dest, history=True)
    dest.touch()                                  # mtime = last use, for eviction
    others = sorted((p for p in root.glob("repo-*") if p != dest and p.is_dir()), key=lambda p: p.stat().st_mtime)
    for old in others[: max(0, len(others) - (MAX_CLONES - 1))]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def ensure_commit(repo: Path, sha: str) -> None:
    """Make `sha` (and its parent) available: fetch it from origin if the bounded clone does not have it."""
    try:
        GitSource(repo, sha)
        GitSource(repo, sha + "^")
        return
    except SourceError:
        pass
    try:
        _git(repo, "fetch", "--no-tags", "--quiet", "--depth=2", "origin", sha)
    except subprocess.SubprocessError as e:
        raise InputError("commit not found in the repository") from e


def _base(r: RepoRow, repo: Path, sha: str) -> BaseModel:
    key = (r.id, sha)
    if key in _bases:
        _bases.move_to_end(key)
        return _bases[key]
    m = base_model(repo, sha, cache=_caches.setdefault(r.id, ParseCache()))     # sandboxed parser (untrusted repo)
    _bases[key] = m
    while len(_bases) > MAX_BASES:
        _bases.popitem(last=False)
    return m


def _finish(repo: Path, r: RepoRow, change: ResolvedChange, base: BaseModel, author: str | None, when: int) -> BlastReport:
    impact = apply_change_paths(propagate(base.graph(PRODUCT), seeds_from(change.changes, base.calls)), change.changes)
    tests = select_tests(base.snapshot, base.calls, change.changes, impact)
    rk = risk(change.changes, impact, base.calls, base.cochange, base.history, base.facts, tests, author,
              base.snapshot, model=_risk_model())
    revs = suggest_reviewers(impact, base.history, when, exclude_email=author)
    return BlastReport(change, base, impact, {}, tests, rk, revs)


def run_blast(r: RepoRow, *, pr_url: str | None = None, commit_sha: str | None = None, diff: str | None = None,
              file_ids: dict[str, int] | None = None) -> dict:
    given = [x for x in (pr_url, commit_sha, diff) if x]
    if len(given) != 1:
        raise InputError("give exactly one of pr_url, commit_sha, diff")
    with _lock:
        repo = ensure_clone(r)
        if commit_sha:
            sha = commit_sha.strip().lower()
            if not SHA.match(sha):
                raise InputError("commit_sha must be 7-40 hex characters")
            ensure_commit(repo, sha)
            rep = analyze_commit(repo, sha, params=PRODUCT, risk_model=_risk_model(),
                                 cache=_caches.setdefault(r.id, ParseCache()),
                                 base=None)
            return to_json(rep, file_ids=file_ids, input_kind="commit", input_ref=sha)
        if pr_url:
            owner, name, number = parse_pr_url(pr_url)
            if f"{owner}/{name}".lower() != r.full_name.lower():
                raise InputError(f"this pull request belongs to {owner}/{name}, not {r.full_name}")
            pr = fetch_pr(owner, name, number)
            change = pr_change(repo, pr)
            base = _base(r, repo, change.base)
            author, when = commit_author(repo, change.head)
            rep = _finish(repo, r, change, base, author, when)
            out = to_json(rep, file_ids=file_ids, input_kind="pr", input_ref=pr_url)
            out["pr"] = {"number": pr.number, "title": pr.title, "author": pr.author, "state": pr.state}
            return out
        # raw diff against the analysed version
        if len(diff.encode("utf-8", errors="replace")) > config.BLAST_MAX_DIFF_BYTES:
            raise InputError(f"diff is larger than {config.BLAST_MAX_DIFF_BYTES // 1024} KB")
        if not r.sha:
            raise InputError("the repository has not been analysed yet")
        ensure_commit(repo, r.sha)
        base = _base(r, repo, r.sha)
        cs = diff_change(diff, GitSource(repo, r.sha).read_text)
        change = ResolvedChange(r.sha, "diff:" + hashlib.sha256(diff.encode()).hexdigest()[:16], diff, cs)
        rep = _finish(repo, r, change, base, None, base.history[0].time if base.history else 0)
        return to_json(rep, file_ids=file_ids, input_kind="diff", input_ref=change.head)


def load_repo(conn, repo_id: int) -> tuple[RepoRow, dict[str, int]]:
    row = conn.execute("SELECT id, url, full_name, last_commit_sha FROM repos WHERE id = %s", (repo_id,)).fetchone()
    if row is None:
        raise InputError("repository not found")
    ids = {p: fid for fid, p in conn.execute("SELECT id, path FROM files WHERE repo_id = %s", (repo_id,))}
    return RepoRow(row[0], row[1], row[2], row[3]), ids
