"""Churn, authors, last-modified and co-change from git history, in ONE `git log` pass."""
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .clone import git_env

SEP = "\x01"
DAY = 86400


@dataclass
class FileGit:
    commits_window: int = 0      # commits touching the file inside the window
    commits_total: int = 0       # ...in all fetched history
    authors: int = 0             # distinct author emails across fetched history
    last_modified: datetime | None = None


@dataclass
class CoChange:
    file_a: str
    file_b: str
    count: int        # commits in the window that touched both
    coupling: float   # count / min(commits_a, commits_b): 1.0 = they always change together


@dataclass
class GitStats:
    files: dict[str, FileGit] = field(default_factory=dict)
    cochange: list[CoChange] = field(default_factory=list)
    commits_seen: int = 0         # commits analysed (shallow-boundary commit excluded)
    window_days: int = 0
    truncated: bool = False       # fetched history is shorter than the requested window
    head_time: datetime | None = None
    error: str | None = None


def _shallow_boundary(repo: Path) -> set[str]:
    f = repo / ".git" / "shallow"
    try:
        return {ln.strip() for ln in f.read_text().splitlines() if ln.strip()}
    except OSError:
        return set()


def _read_log(repo: Path) -> str:
    cmd = [
        "git", "-c", "core.quotepath=false", "-C", str(repo), "log",
        "--no-merges", "--no-renames", "--name-only",
        f"--format=%x01%H%x01%ae%x01%at", f"--max-count={config.HISTORY_MAX_COMMITS}", "HEAD",
    ]
    env = {**git_env(), "GIT_NO_LAZY_FETCH": "1"}  # never fetch blobs/trees from the network here
    out = subprocess.run(cmd, env=env, capture_output=True, text=True, errors="replace",
                         timeout=config.GIT_LOG_TIMEOUT_S, check=True)
    return out.stdout


def collect(repo: Path, tracked: set[str] | None = None, window_days: int | None = None) -> GitStats:
    """Stats for files in `tracked` (None = all). The window ends at the newest commit, so a quiet
    repo still yields meaningful numbers."""
    days = config.HISTORY_WINDOW_DAYS if window_days is None else window_days
    stats = GitStats(window_days=days)
    try:
        raw = _read_log(repo)
    except (subprocess.SubprocessError, OSError) as e:
        stats.error = f"git log failed: {type(e).__name__}"
        return stats

    boundary = _shallow_boundary(repo)
    commits: list[tuple[int, str, list[str]]] = []  # (author time, author email, files)
    oldest_fetched = None  # includes the shallow-boundary commit: it still tells how far back we reach
    skip = True
    for line in raw.splitlines():
        if line.startswith(SEP):
            _, sha, email, at = line.split(SEP)
            skip = sha in boundary  # the oldest commit of a shallow clone "adds" every file: ignore it
            oldest_fetched = int(at) if oldest_fetched is None else min(oldest_fetched, int(at))
            if not skip:
                commits.append((int(at), email.strip().lower(), []))
        elif line and not skip and commits:
            if tracked is None or line in tracked:
                commits[-1][2].append(line)

    if not commits:
        return stats
    stats.commits_seen = len(commits)
    head = max(at for at, _, _ in commits)
    window_start = head - days * DAY
    stats.head_time = datetime.fromtimestamp(head, tz=timezone.utc)
    # truncated = history was cut by the depth limit before reaching the start of the window
    stats.truncated = bool(boundary) and oldest_fetched is not None and oldest_fetched > window_start

    authors: dict[str, set[str]] = {}
    pairs: Counter = Counter()
    for at, email, files in commits:
        in_window = at >= window_start
        for f in files:
            fg = stats.files.setdefault(f, FileGit())
            fg.commits_total += 1
            fg.commits_window += in_window
            authors.setdefault(f, set()).add(email)
            ts = datetime.fromtimestamp(at, tz=timezone.utc)
            if fg.last_modified is None or ts > fg.last_modified:
                fg.last_modified = ts
        # big commits (mass renames, formatting, vendoring) say nothing about coupling
        if in_window and 2 <= len(files) <= config.COCHANGE_MAX_FILES_PER_COMMIT:
            uniq = sorted(set(files))
            for i, a in enumerate(uniq):
                for b in uniq[i + 1:]:
                    pairs[(a, b)] += 1
    for f, fg in stats.files.items():
        fg.authors = len(authors[f])

    ranked = []
    for (a, b), n in pairs.items():
        if n < 2:  # a single shared commit is noise
            continue
        denom = min(stats.files[a].commits_window, stats.files[b].commits_window) or 1
        ranked.append(CoChange(a, b, n, round(n / denom, 4)))
    ranked.sort(key=lambda c: (-c.count, -c.coupling, c.file_a, c.file_b))
    stats.cochange = ranked[: config.COCHANGE_TOP_PAIRS]
    return stats
