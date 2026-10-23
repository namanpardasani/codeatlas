"""Commit history up to (and including) a revision: who changed which files, when.

For the evaluation the revision is the PARENT of the commit being predicted, so the co-change model and every
history-based feature only see the past (no leakage). For the hosted service it is the analysed HEAD.
"""
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..clone import git_env

SEP = "\x01"


@dataclass
class Commit:
    sha: str
    time: int                      # author time, unix seconds
    email: str
    files: list[str] = field(default_factory=list)                    # paths as they were in this commit
    renames: list[tuple[str, str]] = field(default_factory=list)      # (old path, new path) made by this commit
    name: str = ""                                                    # author display name


def canonicalize(commits: list[Commit]) -> list[Commit]:
    """Rewrite every path to its NEWEST name, following renames (commits must be newest first).

    Without this, history before a move (requests/x.py -> src/requests/x.py) is invisible to co-change and churn of the
    current files. Walking from new to old, a rename old->new seen in commit C means: in commits OLDER than C, `old` is
    the file that is now called alias(new)."""
    alias: dict[str, str] = {}
    out: list[Commit] = []
    for c in commits:
        files = sorted({alias.get(f, f) for f in c.files})
        out.append(Commit(c.sha, c.time, c.email, files, c.renames, c.name))
        for old, new in c.renames:
            alias[old] = alias.get(new, new)
    return out


def read_history(repo: Path, rev: str, max_commits: int = 500, since: int | None = None) -> list[Commit]:
    """Newest first. Merges are skipped (their file list repeats the merged branch). Renames are detected (-M) and
    recorded, so `canonicalize` can map old paths to current ones; a renamed file appears in `files` under its new name.
    `since` (unix seconds) bounds the window by time as well as by count."""
    # Rename detection compares file contents. A partial (blobless) clone, as the hosted worker makes, has no old
    # contents locally and lazy fetching is disabled, so there renames are not followed (paths are still correct).
    renames = not is_partial_clone(repo)
    cmd = ["git", "-c", "core.quotepath=false", "-C", str(repo), "log", "--no-merges",
           "-M" if renames else "--no-renames", "--name-status",
           f"--format={SEP}%H{SEP}%ae{SEP}%at{SEP}%an", f"--max-count={max_commits}"]
    if since is not None:
        cmd.append(f"--since={since}")
    cmd += ["--end-of-options", rev]
    out = subprocess.run(cmd, env={**git_env(), "GIT_NO_LAZY_FETCH": "1"}, capture_output=True, text=True,
                         errors="replace", timeout=config.GIT_LOG_TIMEOUT_S, check=True).stdout
    commits: list[Commit] = []
    for line in out.splitlines():
        if line.startswith(SEP):
            _, sha, email, at, name = line.split(SEP, 4)
            commits.append(Commit(sha, int(at), email.strip().lower(), name=name.strip()))
        elif line and commits:
            status, *paths = line.split("\t")
            if status.startswith("R") and len(paths) == 2:
                commits[-1].renames.append((paths[0], paths[1]))
                commits[-1].files.append(paths[1])
            elif paths:
                commits[-1].files.append(paths[-1])
    return commits


def is_partial_clone(repo: Path) -> bool:
    """True for a clone made with --filter (it has a promisor remote: missing objects would be fetched on demand)."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "config", "--get-regexp", r"^remote\..*\.promisor$"],
                             env=git_env(), capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return False
    return "true" in out.stdout


def shallow_boundary(repo: Path) -> set[str]:
    """Commits at the edge of a shallow clone. Their diff against 'nothing' lists every file, so they are dropped."""
    try:
        return {ln.strip() for ln in (repo / ".git" / "shallow").read_text().splitlines() if ln.strip()}
    except OSError:
        return set()
