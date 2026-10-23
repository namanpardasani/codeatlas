"""Walk a cloned repo and produce the list of source files to analyse."""
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import pathspec

from . import config

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", "target", "__pycache__",
    ".venv", "venv", "env", ".tox", ".next", ".nuxt", "coverage", ".idea", ".vscode",
    "bower_components", "third_party", "site-packages",
}
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".lock", ".pb.go", "_pb2.py", ".bundle.js")
SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "go.sum"}

LANGUAGES = {
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".py": "python", ".go": "go", ".java": "java", ".rs": "rust", ".rb": "ruby",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".json": "json", ".md": "markdown", ".yml": "yaml", ".yaml": "yaml", ".sql": "sql",
    ".sh": "shell", ".html": "html", ".css": "css", ".toml": "toml",
}


MAX_GITIGNORE_BYTES = 64 * 1024
MAX_GITIGNORE_LINES = 2000


class InventoryError(Exception):
    pass


@dataclass
class FileRecord:
    path: str  # posix, relative to repo root
    language: str | None
    size: int
    lines: int
    content_hash: str
    is_test: bool


def is_test_path(path: str) -> bool:
    p = path.lower()
    name = p.rsplit("/", 1)[-1]
    parts = p.split("/")
    return (
        any(d in ("test", "tests", "__tests__", "spec", "specs") for d in parts[:-1])
        or name.startswith("test_")
        or name in ("test.js", "test.mjs", "test.cjs", "test.ts", "tests.js", "tests.ts", "test.py", "tests.py")
        or name.endswith(("_test.py", "_test.go", ".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx"))
    )


def skipped_name(fname: str) -> bool:
    """Lockfiles, minified/generated files: never analysed (shared by the checkout walk and git-object snapshots)."""
    return fname in SKIP_NAMES or fname.endswith(SKIP_SUFFIXES)


def skipped_dir(parts: list[str]) -> bool:
    """True when any directory component of a path is vendored / generated (node_modules, dist, ...)."""
    return any(d in SKIP_DIRS for d in parts)


def make_record(rel: str, data: bytes) -> FileRecord | None:
    """FileRecord for one file's bytes, or None when it is not analysed (too big, binary)."""
    if len(data) > config.MAX_FILE_BYTES or _is_binary(data[:8192]):
        return None
    return FileRecord(
        path=rel,
        language=LANGUAGES.get(os.path.splitext(rel)[1].lower()),
        size=len(data),
        lines=data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0),
        content_hash=hashlib.sha256(data).hexdigest(),
        is_test=is_test_path(rel),
    )


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def _load_gitignore(root: Path) -> pathspec.PathSpec | None:
    gi = root / ".gitignore"
    if not gi.is_file() or gi.is_symlink():
        return None
    try:
        # bounded: a hostile .gitignore must not be able to burn CPU in the pattern compiler/matcher
        if gi.stat().st_size > MAX_GITIGNORE_BYTES:
            return None
        lines = gi.read_text(errors="replace").splitlines()[:MAX_GITIGNORE_LINES]
        return pathspec.PathSpec.from_lines("gitignore", [ln for ln in lines if len(ln) <= 300])
    except Exception:
        return None


def build_inventory(root: Path) -> list[FileRecord]:
    root = root.resolve()
    spec = _load_gitignore(root)
    records: list[FileRecord] = []
    seen = 0          # every directory entry looked at, kept or not: a repo of 3 million empty files must not stall the worker

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        # prune vendored / ignored dirs in place
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS
            and not (spec and spec.match_file(f"{rel_dir + '/' if rel_dir else ''}{d}/"))
            and not os.path.islink(os.path.join(dirpath, d))
        )
        seen += len(filenames)
        if seen > config.MAX_WALK_ENTRIES:
            raise InventoryError(f"repo has more than {config.MAX_WALK_ENTRIES} files")
        for fname in sorted(filenames):
            rel = f"{rel_dir}/{fname}" if rel_dir else fname
            full = os.path.join(dirpath, fname)
            if skipped_name(fname):
                continue
            if spec and spec.match_file(rel):
                continue
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            if st.st_size > config.MAX_FILE_BYTES:
                continue
            try:
                data = Path(full).read_bytes()
            except OSError:
                continue
            if _is_binary(data[:8192]):
                continue
            records.append(FileRecord(
                path=rel,
                language=LANGUAGES.get(os.path.splitext(fname)[1].lower()),
                size=st.st_size,
                lines=data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0),
                content_hash=hashlib.sha256(data).hexdigest(),
                is_test=is_test_path(rel),
            ))
            if len(records) > config.MAX_FILES:
                raise InventoryError(f"repo has more than {config.MAX_FILES} source files")
    return records
