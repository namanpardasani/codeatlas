"""Turn raw imports into resolved dependencies (internal files / external packages / unresolved)."""
import posixpath
from collections.abc import Callable, Iterable

from .js import JsResolver
from .python import PyResolver
from .types import ImportItem, ImportResolution, Resolution

JS_EXTS = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}


def resolve_imports(files: set[str], items: Iterable[ImportItem],
                    read_text: Callable[[str], str | None]) -> list[ImportResolution]:
    js = JsResolver(files, read_text)
    py = PyResolver(files)
    out: list[ImportResolution] = []
    for it in items:
        ext = posixpath.splitext(it.from_path)[1].lower()
        if ext in JS_EXTS:
            res = js.resolve(it.from_path, it.specifier)
        elif ext == ".py":
            res = py.resolve(it)
        else:
            res = Resolution("unresolved", reason="unsupported language")
        out.append(ImportResolution(it.from_path, it.idx, it.kind, res))
    return out


def summarize(resolutions: Iterable[ImportResolution]) -> dict[str, int]:
    counts = {"internal": 0, "external": 0, "unresolved": 0}
    for r in resolutions:
        counts[r.resolution.status] += 1
    return counts
