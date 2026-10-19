"""Find the test file that corresponds to a source file ("test-file proximity")."""
import posixpath
import re

def source_stem(path: str) -> str:
    return posixpath.basename(path).split(".")[0]


def test_stem(path: str) -> str | None:
    """'foo.test.ts' -> 'foo', 'test_foo.py' -> 'foo', 'foo_test.py' -> 'foo', 'foo.ts' -> None"""
    name = posixpath.basename(path)
    for marker in (".test.", ".spec."):
        if marker in name:
            return name.split(marker)[0]
    stem = name.split(".")[0]
    m = re.match(r"^test_(.+)$", stem) or re.match(r"^(.+)_(?:test|spec)$", stem)
    return m.group(1) if m else None


def _common_dirs(a: str, b: str) -> int:
    n = 0
    for x, y in zip(posixpath.dirname(a).split("/"), posixpath.dirname(b).split("/")):
        if x != y:
            break
        n += 1
    return n


def map_tests(source_paths: list[str], test_paths: list[str]) -> dict[str, str | None]:
    """source path -> closest test file with a matching name (or None)."""
    by_stem: dict[str, list[str]] = {}
    for t in test_paths:
        s = test_stem(t)
        if s:
            by_stem.setdefault(s, []).append(t)
    out: dict[str, str | None] = {}
    for p in source_paths:
        stems = {source_stem(p)}
        if source_stem(p) in ("index", "__init__", "mod", "main"):
            parent = posixpath.basename(posixpath.dirname(p))
            if parent:
                stems.add(parent)
        cands = sorted({t for s in stems for t in by_stem.get(s, [])})
        out[p] = max(cands, key=lambda t: (_common_dirs(p, t), -len(t), t)) if cands else None
    return out
