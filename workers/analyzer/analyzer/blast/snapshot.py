"""An in-memory model of a repository at one commit: files, parse results, resolved imports, the file import graph.

It reuses the production stages (inventory rules, tree-sitter plugins, import resolvers, graph edges), but writes
nothing to the database. Two callers:
  - hosted service: snapshot of the checkout being analysed (DirSource), or of an analysed repo at a PR's base/head;
  - offline evaluation: snapshot of a repo as it was at a historical commit (GitSource), many times per repo, so
    parse results are cached by (extension, content hash): only files that differ between snapshots are re-parsed.
"""
import posixpath
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol

from ..graph.edges import edges_from_resolutions
from ..graph.types import Edge
from ..inventory import FileRecord
from ..parsing import supported
from ..parsing.runner import SandboxedParser
from ..parsing.types import ParseResult
from ..resolve import resolve_imports
from ..resolve.types import ImportItem, ImportResolution


class Parser(Protocol):
    def parse(self, path: str, source: bytes) -> ParseResult: ...


class InProcessParser:
    """Parses in this process. ONLY for trusted inputs (tests, the offline evaluation's fixed repos): there is no
    timeout or crash isolation. The hosted service always uses SandboxedParser."""

    def parse(self, path: str, source: bytes) -> ParseResult:
        from ..parsing import parse_source
        return parse_source(path, source)


class ParseCache:
    """(extension, sha256) -> ParseResult. A parse result does not depend on the path, only on the bytes and the
    language (chosen by extension), so identical content anywhere, at any commit, is parsed once."""

    def __init__(self) -> None:
        self._d: dict[tuple[str, str], ParseResult] = {}
        self.hits = 0
        self.misses = 0

    def get(self, path: str, content_hash: str) -> ParseResult | None:
        r = self._d.get((posixpath.splitext(path)[1].lower(), content_hash))
        if r is None:
            self.misses += 1
        else:
            self.hits += 1
        return r

    def put(self, path: str, content_hash: str, result: ParseResult) -> None:
        if result.status in ("ok", "partial"):   # failures (timeouts, crashes) are retried next time
            self._d[(posixpath.splitext(path)[1].lower(), content_hash)] = result


@dataclass
class Snapshot:
    label: str
    sha: str | None
    files: dict[str, FileRecord]                       # every analysed file, code or not
    parsed: dict[str, ParseResult]                     # supported (TS/JS/Python) files only
    resolutions: list[ImportResolution]
    import_edges: list[Edge]                           # file A imports file B (code files only)
    imports_of: dict[str, list[str]] = field(default_factory=dict)     # A -> files A imports
    importers_of: dict[str, list[str]] = field(default_factory=dict)   # B -> files that import B
    timings_ms: dict[str, int] = field(default_factory=dict)
    read_text: object = field(default=None, repr=False)     # path -> text in this tree (package.json, configs)
    runner: str | None = field(default=None, repr=False)    # cached test runner detected from package.json

    @property
    def code_files(self) -> list[str]:
        return sorted(self.parsed)

    @property
    def test_files(self) -> list[str]:
        return sorted(p for p, r in self.files.items() if r.is_test)


def build_snapshot(source, *, parser: Parser | None = None, cache: ParseCache | None = None) -> Snapshot:
    """`source`: DirSource or GitSource. `parser`: defaults to a sandboxed child process (safe for untrusted repos)."""
    t: dict[str, int] = {}
    t0 = time.perf_counter()
    files: dict[str, FileRecord] = {}
    data: dict[str, bytes] = {}
    for sf in source.files():
        files[sf.record.path] = sf.record
        if supported(sf.record.path):
            data[sf.record.path] = sf.data
    t["read"] = int((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    parsed: dict[str, ParseResult] = {}
    todo: list[str] = []
    for path in sorted(data):
        hit = cache.get(path, files[path].content_hash) if cache else None
        if hit is not None:
            parsed[path] = hit
        else:
            todo.append(path)
    if todo:
        own = parser is None
        p = SandboxedParser() if own else parser
        try:
            for path in todo:
                res = p.parse(path, data[path])
                parsed[path] = res
                if cache:
                    cache.put(path, files[path].content_hash, res)
        finally:
            if own:
                p.close()
    t["parse"] = int((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    items = [ImportItem(path, i, im.specifier, im.kind, im.names, im.level)
             for path, res in parsed.items() for i, im in enumerate(res.imports)]
    resolutions = resolve_imports(set(files), items, source.read_text)
    edges = edges_from_resolutions(resolutions, set(parsed))
    imports_of: dict[str, set[str]] = defaultdict(set)
    importers_of: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e.source != e.target:
            imports_of[e.source].add(e.target)
            importers_of[e.target].add(e.source)
    t["resolve"] = int((time.perf_counter() - t0) * 1000)

    return Snapshot(
        label=source.label, sha=getattr(source, "sha", None), files=files, parsed=parsed, resolutions=resolutions,
        import_edges=edges,
        imports_of={k: sorted(v) for k, v in sorted(imports_of.items())},
        importers_of={k: sorted(v) for k, v in sorted(importers_of.items())},
        timings_ms=t,
        read_text=source.read_text,
    )
