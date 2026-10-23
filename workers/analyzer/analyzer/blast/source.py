"""Where a snapshot's files come from: a checked-out directory, or git objects at any commit (no checkout needed).

Both apply the inventory's rules (skipped dirs/names, size limit, binary detection) so a snapshot of commit X built from
git objects sees the same files the normal pipeline would see after checking X out. One difference: .gitignore is not
applied to git objects, because committed files are tracked by definition (a tracked file that matches .gitignore is
still part of the code).
"""
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..clone import git_env
from ..inventory import FileRecord, build_inventory, make_record, skipped_dir, skipped_name

GIT_TIMEOUT_S = 120


class SourceError(Exception):
    pass


@dataclass
class SourceFile:
    record: FileRecord
    data: bytes


class DirSource:
    """A checkout on disk (the normal pipeline's input)."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.label = str(root)

    def files(self) -> Iterator[SourceFile]:
        for rec in build_inventory(self.root):
            full = (self.root / rec.path).resolve()
            if not full.is_relative_to(self.root):
                continue
            try:
                yield SourceFile(rec, full.read_bytes())
            except OSError:
                continue

    def read_text(self, path: str) -> str | None:
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root):
            return None
        try:
            return full.read_bytes().decode("utf-8", errors="replace")   # no newline translation (CRLF stays CRLF)
        except OSError:
            return None


def _git(repo: Path, *args: str, input_: bytes | None = None) -> bytes:
    try:
        out = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(repo), *args], input=input_,
                             env=git_env(), capture_output=True, timeout=GIT_TIMEOUT_S, check=True)
    except subprocess.CalledProcessError as e:
        raise SourceError(f"git {args[0]} failed: {e.stderr.decode(errors='replace')[:200]}") from e
    except (subprocess.SubprocessError, OSError) as e:
        raise SourceError(f"git {args[0]} failed: {type(e).__name__}") from e
    return out.stdout


def resolve_rev(repo: Path, rev: str) -> str:
    """Full SHA of a revision (commit-ish); raises SourceError if it does not exist."""
    return _git(repo, "rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}").decode().strip()


class GitSource:
    """The tree of one commit, read straight from the object store (`ls-tree` + one `cat-file --batch`)."""

    def __init__(self, repo: Path, rev: str):
        self.repo = repo
        self.sha = resolve_rev(repo, rev)
        self.label = f"{repo}@{self.sha[:12]}"
        self._entries: dict[str, tuple[str, int]] | None = None   # path -> (blob sha, size)

    def entries(self) -> dict[str, tuple[str, int]]:
        if self._entries is None:
            raw = _git(self.repo, "ls-tree", "-r", "-z", "--long", "--full-tree", self.sha)
            out: dict[str, tuple[str, int]] = {}
            for item in raw.split(b"\0"):
                if not item:
                    continue
                meta, _, path_b = item.partition(b"\t")
                mode, kind, obj, size = meta.split()
                path = path_b.decode("utf-8", errors="replace")
                # regular files only: no symlinks (120000), no submodules (commit entries)
                if kind != b"blob" or mode not in (b"100644", b"100755"):
                    continue
                parts = path.split("/")
                if skipped_dir(parts[:-1]) or skipped_name(parts[-1]):
                    continue
                n = int(size)
                if n > config.MAX_FILE_BYTES:
                    continue
                out[path] = (obj.decode(), n)
            if len(out) > config.MAX_FILES:
                raise SourceError(f"repo has more than {config.MAX_FILES} source files")
            self._entries = dict(sorted(out.items()))
        return self._entries

    def _blobs(self, shas: list[str]) -> list[bytes]:
        """Contents of many blobs in one `git cat-file --batch` round trip."""
        if not shas:
            return []
        raw = _git(self.repo, "cat-file", "--batch", input_=("\n".join(shas) + "\n").encode())
        out: list[bytes] = []
        pos = 0
        for _ in shas:
            nl = raw.index(b"\n", pos)
            header = raw[pos:nl].split()
            if len(header) < 3 or header[1] == b"missing":
                raise SourceError(f"blob {header[0].decode(errors='replace')} missing")
            size = int(header[2])
            out.append(raw[nl + 1: nl + 1 + size])
            pos = nl + 1 + size + 1          # content is followed by a newline
        return out

    def files(self) -> Iterator[SourceFile]:
        items = list(self.entries().items())
        for i in range(0, len(items), 500):
            chunk = items[i:i + 500]
            for (path, _), data in zip(chunk, self._blobs([obj for _, (obj, _) in chunk])):
                rec = make_record(path, data)
                if rec is not None:
                    yield SourceFile(rec, data)

    def read_text(self, path: str) -> str | None:
        e = self.entries().get(path)
        if e is None:
            return None
        try:
            return self._blobs([e[0]])[0].decode("utf-8", errors="replace")
        except SourceError:
            return None
