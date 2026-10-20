"""Resolve Python imports to files in the repo."""
import posixpath
import sys

from .types import ImportItem, Resolution

STDLIB = frozenset(sys.stdlib_module_names)


class PyResolver:
    def __init__(self, files: set[str]):
        self.files = files
        py = [p for p in files if p.endswith(".py")]
        self.ns_dirs = {d for p in py for d in self._ancestors(p)}  # any dir that contains .py
        self.roots = self._find_roots(py)

    @staticmethod
    def _ancestors(path: str):
        d = posixpath.dirname(path)
        while d:
            yield d
            d = posixpath.dirname(d)

    def _is_pkg(self, d: str) -> bool:
        return posixpath.join(d, "__init__.py") in self.files

    def _find_roots(self, py: list[str]) -> list[str]:
        """Import roots (what sys.path would point at): repo root, plus the parent of every
        top-level package (handles `src/pkg/...` layouts), plus src/ and lib/ if present."""
        roots = {""}
        for p in py:
            d = posixpath.dirname(p)
            top = None
            while d and self._is_pkg(d):
                top = d
                d = posixpath.dirname(d)
            if top is not None:
                roots.add(posixpath.dirname(top))
        for common in ("src", "lib"):
            if common in self.ns_dirs:
                roots.add(common)
        return sorted(roots, key=lambda r: (r.count("/") if r else -1, r))

    def _find_module(self, root: str, parts: list[str]):
        """('file', path) | ('namespace', dir) | None. Regular package beats module of same name."""
        base = posixpath.join(root, *parts) if parts else root
        base = base.rstrip("/")
        init = posixpath.join(base, "__init__.py") if base else "__init__.py"
        if init in self.files:
            return "file", init
        if parts and base + ".py" in self.files:
            return "file", base + ".py"
        if base in self.ns_dirs:
            return "namespace", base
        return None

    def _search_roots(self, from_path: str) -> list[str]:
        here = posixpath.dirname(from_path)  # scripts can import siblings (sys.path[0])
        return self.roots + ([here] if here not in self.roots else [])

    def _submodule_targets(self, root: str, parts: list[str], names: list[str]) -> tuple[list[str], bool]:
        """Files of the names that are submodules, and whether EVERY imported name is one (no attribute, no `*`)."""
        out, all_sub = [], bool(names)
        for n in names:
            if n == "*":
                all_sub = False
                continue
            m = self._find_module(root, parts + [n])
            if m and m[0] == "file":
                out.append(m[1])
            else:
                all_sub = False
        return out, all_sub

    @staticmethod
    def _combine(package_file: str | None, subs: list[str], all_sub: bool) -> list[str]:
        """`from pkg import a, b` where a and b are submodules depends on pkg/a.py and pkg/b.py. The package's own
        __init__.py only runs as a side effect; counting it would make every child "import" its parent, which
        re-exports the children and fabricates cycles. Keep it when some name is defined in __init__ itself."""
        targets = list(subs)
        if package_file and not (subs and all_sub):
            targets.append(package_file)
        return sorted(dict.fromkeys(targets))

    def resolve(self, item: ImportItem) -> Resolution:
        if item.level > 0:
            return self._resolve_relative(item)
        parts = item.specifier.split(".") if item.specifier else []
        if not parts:
            return Resolution("unresolved", reason="empty module name")
        for root in self._search_roots(item.from_path):
            found = self._find_module(root, parts)
            if not found:
                continue
            pkg_file = found[1] if found[0] == "file" else None
            subs, all_sub = self._submodule_targets(root, parts, item.names) if item.kind == "from" else ([], False)
            targets = self._combine(pkg_file, subs, all_sub)
            if targets:
                return Resolution("internal", targets)
            return Resolution("unresolved", reason=f"namespace package {'.'.join(parts)} has no matching module")
        top = parts[0]
        if top in STDLIB:
            return Resolution("external", package=top, reason="stdlib")
        for root in self._search_roots(item.from_path):
            if self._find_module(root, [top]):
                return Resolution("unresolved", reason=f"package {top} is in the repo but {item.specifier} was not found")
        return Resolution("external", package=top)

    def _resolve_relative(self, item: ImportItem) -> Resolution:
        base = posixpath.dirname(item.from_path)
        depth = len(base.split("/")) if base else 0
        if item.level - 1 > depth:
            return Resolution("unresolved", reason="relative import goes beyond the repository root")
        for _ in range(item.level - 1):
            base = posixpath.dirname(base)
        parts = item.specifier.split(".") if item.specifier else []
        found = self._find_module(base, parts)
        pkg_file = found[1] if found and found[0] == "file" else None
        subs, all_sub = self._submodule_targets(base, parts, item.names) if item.kind == "from" else ([], False)
        targets = self._combine(pkg_file, subs, all_sub)
        if targets:
            return Resolution("internal", targets)
        return Resolution("unresolved", reason="relative import target not found")
