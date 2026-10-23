"""Finding bug-fixing commits and, with SZZ, the commits that introduced the bugs.

SZZ (Sliwerski, Zimmermann, Zeller 2005) in one sentence: the lines a bug fix deletes or modifies are the buggy lines,
so the commit that last touched those lines before the fix probably introduced the bug.

Our variant (a "B-SZZ" with the usual noise filters):
  - fix commits: subject says fix/bug/regression/crash/broken/incorrect/wrong..., not typo/docs/ci/lint/release/
    dependency bumps; not a merge; touches at most MAX_FIX_FILES files; modifies at least one existing non-test source
    file (a fix made only of new lines has nothing to blame: SZZ cannot handle it, so it is skipped and counted);
  - only deleted / modified lines of non-test source files are blamed; blank lines and comment-only lines are skipped;
  - `git blame -w -M -C`: ignore whitespace, follow lines moved or copied between files, so a reformat or a move is
    not mistaken for the origin;
  - mass-formatting / huge commits are ignored by blame (--ignore-rev): they touch every line and would be blamed for
    every bug;
  - the inducing commit is the blamed commit owning the most blamed lines (ties: the most recent), and it must itself
    be a normal commit (not a merge, not huge, touching source code).

Known noise (why we validate a sample by hand): the blamed line may have been correct and the bug elsewhere; a fix may
also refactor; the "real" cause may be several commits; tangled commits mix unrelated work.
"""
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ...parsing import supported
from ...inventory import is_test_path

FIX_RE = re.compile(r"\b(fix(e[sd]|ing)?|bug(fix)?|regression|crash(es|ing)?|broken|incorrect(ly)?|wrong(ly)?|"
                    r"resolves?|hang(s|ing)?|leak(s|ing)?|fails?|failing)\b", re.I)
NOT_FIX_RE = re.compile(r"\b(typos?|docs?|documentation|readme|changelog|lint(ing|er)?|format(ting)?|prettier|ci|"
                        r"bump(s|ed)?|upgrade|deps?|dependenc(y|ies)|dependabot|release|version|revert|spelling|"
                        r"grammar|test(s|ing)? only|flaky|coverage|benchmark)\b", re.I)
FORMAT_RE = re.compile(r"\b(black|prettier|reformat|format(ting)?|isort|ruff|eslint|lint|whitespace|style|pyupgrade|"
                       r"standard(js)?|xo)\b", re.I)
# fixes that change no runtime behaviour: type-checker findings, annotations, typings
NON_FUNCTIONAL_RE = re.compile(r"\b(mypy|pyright|typing|type hints?|annotations?|types?|typings?|tsc|dts)\b", re.I)
MAX_FIX_FILES = 10
HUGE_COMMIT = 60
SEP = "\x01"


def git(repo: Path, *args: str, timeout: int = 300) -> str:
    return subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(repo), *args], capture_output=True,
                          timeout=timeout, check=True).stdout.decode("utf-8", errors="replace")


@dataclass
class CommitInfo:
    sha: str
    parents: list[str]
    time: int
    author: str
    subject: str
    files: dict[str, str] = field(default_factory=dict)     # path -> status letter (A/M/D/R...)


def log_commits(repo: Path, head: str) -> list[CommitInfo]:
    """Every commit reachable from `head` with its changed files (first-parent diff for merges is not listed:
    merges are excluded from both fixes and inducers anyway)."""
    out = git(repo, "log", "--no-renames", "--name-status", f"--format={SEP}%H{SEP}%P{SEP}%at{SEP}%an{SEP}%s", head,
              timeout=900)
    commits: list[CommitInfo] = []
    for line in out.split("\n"):
        if line.startswith(SEP):
            _, sha, parents, at, an, subj = line.split(SEP, 5)
            commits.append(CommitInfo(sha, parents.split(), int(at), an, subj.strip()))
        elif line and commits and "\t" in line:
            status, path = line.split("\t", 1)
            commits[-1].files[path.split("\t")[-1]] = status[0]
    return commits


def is_source(path: str) -> bool:
    return supported(path) and not is_test_path(path) and not path.endswith(".d.ts")


def is_fix(c: CommitInfo) -> tuple[bool, str]:
    if len(c.parents) != 1:
        return False, "merge"
    if not FIX_RE.search(c.subject):
        return False, "message"
    if NOT_FIX_RE.search(c.subject):
        return False, "excluded-message"
    if len(c.files) > MAX_FIX_FILES:
        return False, "too-many-files"
    if not any(s == "M" and is_source(p) for p, s in c.files.items()):
        return False, "no-modified-source"
    if NON_FUNCTIONAL_RE.search(c.subject):
        return False, "non-functional-message"
    return True, "ok"


def functional_change(repo: Path, sha: str, parser=None) -> bool:
    """True when the commit makes at least one REAL code change in a non-test source file: a symbol whose code
    fingerprint changed, or module-level code beyond import lines. Comment, docstring, whitespace and `# type: ignore`
    edits keep fingerprints equal, so documentation-only "fixes" are filtered out (Phase 2 change analysis)."""
    from ..inputs import commit_change
    res = commit_change(repo, sha, parser=parser)
    for f in res.changes.files:
        if f.category != "code" or not is_source(f.path):
            continue
        if f.semantic_symbols or (f.module_changed and not f.imports_only) or f.error:
            return True
    return False


def formatting_commits(commits: list[CommitInfo]) -> set[str]:
    """Commits blame should look through: huge commits (mass renames, vendoring, reformat runs) and commits whose
    subject says they only reformat."""
    out = set()
    for c in commits:
        n_src = sum(1 for p in c.files if supported(p))
        if n_src > HUGE_COMMIT or (FORMAT_RE.search(c.subject) and n_src > 5):
            out.add(c.sha)
    return out


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def deleted_lines(repo: Path, parent: str, sha: str, path: str) -> list[int]:
    """Old-side line numbers the fix deleted or modified in `path` (unified=0: no context lines)."""
    out = git(repo, "diff", "-U0", "-w", "--no-color", "--no-ext-diff", parent, sha, "--", path)
    lines: list[int] = []
    for ln in out.split("\n"):
        m = _HUNK.match(ln)
        if m:
            start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            lines.extend(range(start, start + count))
    return lines


def _comment_only(text: str, path: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if path.endswith(".py"):
        return t.startswith("#") or t in ('"""', "'''")
    return t.startswith(("//", "/*", "*", "*/"))


def blame(repo: Path, parent: str, path: str, lines: list[int], ignore: set[str]) -> Counter:
    """Blamed commit -> number of the given lines it last touched (as of `parent`)."""
    if not lines:
        return Counter()
    src = git(repo, "show", f"{parent}:{path}").split("\n")
    keep = [n for n in lines if 1 <= n <= len(src) and not _comment_only(src[n - 1], path)]
    if not keep:
        return Counter()
    args = ["blame", "--porcelain", "-w", "-M", "-C"]
    for sha in sorted(ignore):
        args += ["--ignore-rev", sha]
    for n in keep:
        args += ["-L", f"{n},{n}"]
    out = git(repo, *args, parent, "--", path)
    counts: Counter = Counter()
    for ln in out.split("\n"):
        m = re.match(r"^([0-9a-f]{40}) \d+ \d+(?: (\d+))?$", ln)
        if m and m.group(2) is not None:            # header line of a group: "<sha> <orig> <final> <count>"
            counts[m.group(1)] += int(m.group(2))
    return counts


@dataclass
class Pair:
    repo: str
    fix: str
    fix_subject: str
    fix_time: int
    inducing: str
    inducing_subject: str
    inducing_time: int
    blamed_lines: int                 # lines of the fix blamed on the inducing commit
    total_blamed: int                 # all blamed lines of this fix
    candidates: int                   # distinct commits blamed
    fix_files: dict[str, str]         # files the fix touched (path -> status)
    inducing_files: dict[str, str]
    references_issue: bool

    @property
    def id(self) -> str:
        return f"{self.repo.split('/')[-1]}:{self.inducing[:8]}->{self.fix[:8]}"

    def to_json(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d


def mine(repo: Path, name: str, head: str, limit: int, log=print, *, semantic_filter: bool = True,
         parser=None, skip_fixes: set[str] | None = None) -> tuple[list[Pair], Counter]:
    """Most recent fixes first, until `limit` pairs are found."""
    commits = log_commits(repo, head)
    by_sha = {c.sha: c for c in commits}
    ignore = formatting_commits(commits)
    stats: Counter = Counter()
    pairs: list[Pair] = []
    for c in commits:
        ok, why = is_fix(c)
        stats[f"fix:{why}"] += 1
        if not ok:
            continue
        if skip_fixes and c.sha in skip_fixes:          # already in another split (development set)
            stats["skipped:other-split"] += 1
            continue
        if semantic_filter and not functional_change(repo, c.sha, parser):
            stats["fix:non-functional-change"] += 1
            continue
        parent = c.parents[0]
        counts: Counter = Counter()
        for path, status in c.files.items():
            if status == "M" and is_source(path):
                try:
                    counts += blame(repo, parent, path, deleted_lines(repo, parent, c.sha, path), ignore)
                except subprocess.CalledProcessError:
                    stats["blame-error"] += 1
        if not counts:
            stats["szz:nothing-to-blame"] += 1          # pure additions, or only comment/blank lines changed
            continue
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -(by_sha[kv[0]].time if kv[0] in by_sha else 0)))
        chosen = None
        for sha, n in ranked:
            ic = by_sha.get(sha)
            if ic is None or len(ic.parents) != 1 or sha in ignore or not any(is_source(p) for p in ic.files):
                continue
            chosen = (ic, n)
            break
        if chosen is None:
            stats["szz:no-valid-inducer"] += 1
            continue
        ic, n = chosen
        pairs.append(Pair(name, c.sha, c.subject[:200], c.time, ic.sha, ic.subject[:200], ic.time, n,
                          sum(counts.values()), len(counts), dict(c.files), dict(ic.files),
                          bool(re.search(r"#\d+|\b(close[sd]?|fix(e[sd])?|resolve[sd]?) #\d+", c.subject, re.I))))
        stats["pairs"] += 1
        if len(pairs) >= limit:
            break
    log(f"{name}: {len(commits)} commits, {stats['pairs']} pairs, {dict(stats)}")
    return pairs, stats
