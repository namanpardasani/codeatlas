"""Diff -> changed symbols: which functions, classes and files a change really touches, and how.

For every changed file the OLD and the NEW version are parsed, so:
  - a deleted function is found in the old version, an added one in the new version;
  - each changed line is attributed to the INNERMOST symbol that contains it (a method, not its whole class), using
    old-side numbers for deleted lines and new-side numbers for added lines;
  - a symbol present in both versions is compared by body fingerprint (Phase 0): equal = cosmetic (comments,
    whitespace, docstrings, a move inside the file), else `signature` if its parameters / export status changed, else
    `body`;
  - unmatched old/new symbols are paired up: same code under another name = `renamed`; same name and code in another
    file = `moved`; the rest are `deleted` / `added`;
  - lines outside every symbol are module-level code (imports, constants): a change there counts only if the
    module fingerprint changed.

Change kinds and what they mean downstream (Phase 3 propagation):
  signature  callers may break                        body     behaviour may change for callers
  added      nothing calls it yet (its own calls matter) deleted  every caller breaks
  renamed    every caller breaks (the name is gone)      moved    importers of the old file break, behaviour same
  cosmetic   ignored                                     module   everything importing the file may be affected
                                                         (much less so when only its import lines changed)
"""
import posixpath
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from ..inventory import SKIP_NAMES, is_test_path
from ..parsing import supported
from ..parsing.runner import SandboxedParser
from ..parsing.types import ParseResult, Symbol
from .callgraph import SymRef
from .diff import DiffError, FileDiff, apply_patch, parse_diff

Reader = Callable[[str], str | None]

DOC_EXT = {".md", ".rst", ".txt", ".adoc", ".markdown"}
CONFIG_EXT = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".properties", ".conf"}
BUILD_NAMES = {"dockerfile", "makefile", "package.json", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini",
               "requirements.txt", "pipfile", "tsconfig.json", "jsconfig.json", ".babelrc", "babel.config.js",
               "webpack.config.js", "rollup.config.js", "vite.config.ts", "vite.config.js", "noxfile.py",
               "manifest.in", "cmakelists.txt", ".nvmrc", ".python-version", "lerna.json", "pnpm-workspace.yaml"}
TEST_SETUP_NAMES = {"conftest.py", "jest.config.js", "jest.config.ts", "jest.setup.js", "jest.setup.ts",
                    "vitest.config.ts", "vitest.config.js", "vitest.setup.ts", "setuptests.ts", "setuptests.js",
                    "pytest.ini", "karma.conf.js", ".mocharc.js", ".mocharc.json", ".mocharc.yml"}


def categorize(path: str) -> str:
    """code | test | test_setup | config | build | docs | lockfile | other. Test setup and build/config changes are
    the ones Phase 4 answers with "run the full suite"."""
    name = posixpath.basename(path).lower()
    ext = posixpath.splitext(name)[1]
    if name in SKIP_NAMES or ext == ".lock":
        return "lockfile"
    if name in TEST_SETUP_NAMES or re.match(r"^(jest|vitest|playwright|cypress)\.(config|setup)\.", name):
        return "test_setup"
    if name in BUILD_NAMES or path.startswith(".github/") or name.startswith("tsconfig") \
            or re.match(r"^requirements[-\w]*\.txt$", name) or re.search(r"\.config\.(c|m)?(js|ts)$", name):
        return "build"
    if supported(path):
        return "test" if is_test_path(path) else "code"
    if ext in DOC_EXT or path.startswith("docs/"):
        return "docs"
    if ext in CONFIG_EXT or name.startswith(".env"):
        return "config"
    return "other"


@dataclass
class SymbolChange:
    change: str                     # signature | body | added | deleted | renamed | moved | cosmetic
    kind: str                       # function | method | class | ...
    name: str                       # qualified: Class.method
    old: SymRef | None              # in the OLD tree (path = old path)
    new: SymRef | None              # in the NEW tree
    lines_old: list[int] = field(default_factory=list)   # changed old-side lines inside this symbol
    lines_new: list[int] = field(default_factory=list)
    note: str = ""                  # e.g. "renamed from parse", "moved from a.py"

    @property
    def semantic(self) -> bool:
        return self.change != "cosmetic"


@dataclass
class FileChange:
    path: str                       # new path (old path for deletions)
    old_path: str | None
    status: str                     # added | deleted | modified | renamed | binary | mode_only
    category: str
    added_lines: int = 0
    deleted_lines: int = 0
    symbols: list[SymbolChange] = field(default_factory=list)
    module_changed: bool = False    # module-level code (imports, constants, top-level statements) changed
    imports_only: bool = False      # ...and only import statements differ (no constant / statement changed)
    error: str | None = None        # e.g. the diff does not apply to the base version
    lines_old: set[int] = field(default_factory=set, repr=False)   # deleted lines (old numbering)
    lines_new: set[int] = field(default_factory=set, repr=False)   # added lines (new numbering)

    @property
    def semantic_symbols(self) -> list[SymbolChange]:
        return [s for s in self.symbols if s.semantic]

    @property
    def cosmetic_only(self) -> bool:
        return self.category in ("code", "test") and not self.module_changed and not self.semantic_symbols \
            and self.status in ("modified", "renamed") and self.error is None and self.old_path == self.path


@dataclass
class ChangeSet:
    files: list[FileChange] = field(default_factory=list)
    old_parsed: dict[str, ParseResult] = field(default_factory=dict)   # by old path
    new_parsed: dict[str, ParseResult] = field(default_factory=dict)   # by new path

    @property
    def changed_symbols(self) -> list[SymbolChange]:
        return [s for f in self.files for s in f.semantic_symbols]

    def stats(self) -> dict[str, int]:
        c: Counter = Counter()
        for f in self.files:
            c[f"files:{f.category}"] += 1
            for s in f.symbols:
                c[f"symbols:{s.change}"] += 1
            c["module_changes"] += f.module_changed
            c["errors"] += f.error is not None
        return dict(c)


# ---- line -> symbol attribution ------------------------------------------------------------------------------------

def touched_symbols(symbols: list[Symbol], lines: set[int]) -> tuple[dict[int, list[int]], list[int]]:
    """Attribute changed lines to symbols. Returns ({symbol index: [its changed lines]}, [lines outside every symbol]).

    A line belongs to the INNERMOST symbol whose [start_line, end_line] contains it: a change inside a method is a
    change to that method, not to the whole class (the class is reported only for lines of its own, such as a class
    attribute). Ties (two symbols with the same range, e.g. `export default function`) go to the later one in the list.
    Ranges are inclusive and 1-based, like the line numbers of a unified diff.
    """
    by_sym: dict[int, list[int]] = {}
    outside: list[int] = []
    # sort candidates by span so the first match is the innermost; O(lines x symbols) is fine for diff-sized inputs
    order = sorted(range(len(symbols)), key=lambda i: (symbols[i].end_line - symbols[i].start_line, -i))
    for ln in sorted(lines):
        hit = next((i for i in order if symbols[i].start_line <= ln <= symbols[i].end_line), None)
        if hit is None:
            outside.append(ln)
        else:
            by_sym.setdefault(hit, []).append(ln)
    return by_sym, outside


def _qual(s: Symbol) -> str:
    return f"{s.parent}.{s.name}" if s.parent else s.name


def _keys(symbols: list[Symbol]) -> dict[tuple, int]:
    """Identity of a symbol across versions: (kind, parent, name, n-th occurrence). Overloads get distinct keys."""
    seen: Counter = Counter()
    out: dict[tuple, int] = {}
    for i, s in enumerate(symbols):
        base = (s.kind, s.parent, s.name)
        out[(*base, seen[base])] = i
        seen[base] += 1
    return out


def _signature_changed(o: Symbol, n: Symbol) -> bool:
    return o.params != n.params or o.is_exported != n.is_exported or o.is_default_export != n.is_default_export \
        or o.bases != n.bases


def _text_without_name(text: list[str], s: Symbol) -> str:
    body = "\n".join(text[s.start_line - 1:s.end_line])
    body = re.sub(rf"\b{re.escape(s.name)}\b", "\x00", body)
    return re.sub(r"\s+", " ", body).strip()


# ---- per file ------------------------------------------------------------------------------------------------------

def _compare(fd: FileDiff, fc: FileChange, old: ParseResult | None, new: ParseResult | None,
             old_text: str, new_text: str) -> None:
    o_syms = old.symbols if old else []
    n_syms = new.symbols if new else []
    o_lines, n_lines = old_text.split("\n"), new_text.split("\n")
    # blank lines carry no code: an empty line added between two methods must not mark the whole class as changed
    o_hit, o_out = touched_symbols(o_syms, {ln for ln in fd.deleted if ln <= len(o_lines) and o_lines[ln - 1].strip()})
    n_hit, n_out = touched_symbols(n_syms, {ln for ln in fd.added if ln <= len(n_lines) and n_lines[ln - 1].strip()})
    if fd.status == "added":
        n_hit = {i: list(range(s.start_line, s.end_line + 1)) for i, s in enumerate(n_syms)}
    if fd.status == "deleted":
        o_hit = {i: list(range(s.start_line, s.end_line + 1)) for i, s in enumerate(o_syms)}

    o_keys, n_keys = _keys(o_syms), _keys(n_syms)
    o_key_of = {i: k for k, i in o_keys.items()}
    n_key_of = {i: k for k, i in n_keys.items()}
    old_path, new_path = fd.old_path or "", fd.new_path or ""

    done_old: set[int] = set()
    done_new: set[int] = set()
    for i in sorted(set(o_hit) | {o_keys[n_key_of[j]] for j in n_hit if n_key_of[j] in o_keys}):
        k = o_key_of[i]
        if k not in n_keys:
            continue
        j = n_keys[k]
        o, n = o_syms[i], n_syms[j]
        if o.body_hash == n.body_hash:
            change = "cosmetic"
        elif _signature_changed(o, n):
            change = "signature"
        else:
            change = "body"
        fc.symbols.append(SymbolChange(change, n.kind, _qual(n), SymRef(old_path, i), SymRef(new_path, j),
                                       o_hit.get(i, []), n_hit.get(j, [])))
        done_old.add(i)
        done_new.add(j)

    gone = [i for i in sorted(o_hit) if i not in done_old and o_key_of[i] not in n_keys]
    born = [j for j in sorted(n_hit) if j not in done_new and n_key_of[j] not in o_keys]
    for i in list(gone):                       # same code, new name, same place in the hierarchy -> renamed
        o = o_syms[i]
        shape = _text_without_name(o_lines, o)
        match = next((j for j in born if n_syms[j].kind == o.kind and n_syms[j].parent == o.parent
                      and _text_without_name(n_lines, n_syms[j]) == shape), None)
        if match is not None:
            n = n_syms[match]
            fc.symbols.append(SymbolChange("renamed", n.kind, _qual(n), SymRef(old_path, i), SymRef(new_path, match),
                                           o_hit[i], n_hit[match], note=f"renamed from {_qual(o)}"))
            gone.remove(i)
            born.remove(match)
    for i in gone:
        o = o_syms[i]
        fc.symbols.append(SymbolChange("deleted", o.kind, _qual(o), SymRef(old_path, i), None, o_hit[i], []))
    for j in born:
        n = n_syms[j]
        fc.symbols.append(SymbolChange("added", n.kind, _qual(n), None, SymRef(new_path, j), [], n_hit[j]))

    module_lines = set(o_out) | set(n_out)
    if fd.status in ("added", "deleted"):
        fc.module_changed = bool((new or old) and (new or old).module_hash != _EMPTY_MODULE)
    elif module_lines:
        fc.module_changed = (old.module_hash if old else "") != (new.module_hash if new else "")
        fc.imports_only = fc.module_changed and old is not None and new is not None \
            and old.module_code_hash == new.module_code_hash


_EMPTY_MODULE = "da39a3ee5e6b4b0d"            # sha1 of b"" (first 16 hex): a file with no module-level code


def _pair_moves(files: list[FileChange], old_parsed: dict[str, ParseResult], new_parsed: dict[str, ParseResult]) -> None:
    """A function deleted from one file and added, with identical code and name, to another = moved."""
    added = {}
    for f in files:
        for s in f.symbols:
            if s.change == "added" and s.new is not None:
                sym = new_parsed[s.new.path].symbols[s.new.idx]
                added.setdefault((sym.kind, sym.name, sym.body_hash), []).append((f, s))
    for f in files:
        for s in list(f.symbols):
            if s.change != "deleted" or s.old is None:
                continue
            sym = old_parsed[s.old.path].symbols[s.old.idx]
            cands = [x for x in added.get((sym.kind, sym.name, sym.body_hash), []) if x[1].change == "added"]
            if len(cands) == 1:
                f2, s2 = cands[0]
                s2.change, s2.old, s2.lines_old, s2.note = "moved", s.old, s.lines_old, f"moved from {s.old.path}"
                f.symbols.remove(s)


def analyze_change(diff_text: str, old: Reader, new: Reader | None = None, *, parser=None,
                   file_diffs: list[FileDiff] | None = None) -> ChangeSet:
    """`old(path)` reads a file in the base version. `new(path)` reads it in the changed version; when None (a raw diff
    uploaded against an analysed repo) the new version is rebuilt by applying the patch to the base, which also proves
    the diff fits the base: if it doesn't, that file gets an `error` and only its file-level facts are reported.
    `parser`: defaults to the sandboxed child process (diffs and PR contents are untrusted)."""
    fds = file_diffs if file_diffs is not None else parse_diff(diff_text)
    cs = ChangeSet()
    own = parser is None
    p = SandboxedParser() if own else parser
    try:
        for fd in fds:
            path = fd.path
            fc = FileChange(path=path, old_path=fd.old_path, status=fd.status, category=categorize(path),
                            added_lines=len(fd.added), deleted_lines=len(fd.deleted),
                            lines_old=set(fd.deleted), lines_new=set(fd.added))
            cs.files.append(fc)
            if fd.status in ("binary", "mode_only") or not supported(path) or (fd.old_path and not supported(fd.old_path)):
                continue
            old_text = (old(fd.old_path) if fd.old_path else "") or ""
            if fd.old_path and old(fd.old_path) is None:
                fc.error = "base version of the file is not available"
                continue
            if fd.status == "deleted":
                new_text = ""
            elif new is not None:
                got = new(fd.new_path) if fd.new_path else ""
                if got is None:
                    fc.error = "changed version of the file is not available"
                    continue
                new_text = got
            else:
                try:
                    new_text = apply_patch(old_text, fd) if fd.hunks else old_text
                except DiffError as e:
                    fc.error = f"diff does not apply to the analysed version: {e}"
                    continue
            old_res = p.parse(fd.old_path, old_text.encode()) if fd.old_path else None
            new_res = p.parse(fd.new_path, new_text.encode()) if fd.new_path else None
            if old_res is not None:
                cs.old_parsed[fd.old_path] = old_res
            if new_res is not None:
                cs.new_parsed[fd.new_path] = new_res
            if (old_res and old_res.status == "failed") or (new_res and new_res.status == "failed"):
                fc.error = "file could not be parsed"
                continue
            if fd.status == "renamed" and not fd.hunks:
                # pure move of the whole file: every symbol moved; importers of the old path are affected
                for i, s in enumerate(new_res.symbols if new_res else []):
                    fc.symbols.append(SymbolChange("moved", s.kind, _qual(s), SymRef(fd.old_path, i), SymRef(fd.new_path, i),
                                                   note=f"file moved from {fd.old_path}"))
                continue
            _compare(fd, fc, old_res, new_res, old_text, new_text)
    finally:
        if own:
            p.close()
    _pair_moves(cs.files, cs.old_parsed, cs.new_parsed)
    for f in cs.files:
        f.symbols.sort(key=lambda s: (s.change == "cosmetic", s.name))
    return cs
