"""Resolve TS/JS import specifiers to files in the repo."""
import posixpath
import re
from collections.abc import Callable

from .jsonc import parse_jsonc
from .types import Resolution

TS_FIRST = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".json", ".d.ts")
# `import "./a.js"` in TS source means a.ts / a.tsx (ESM convention): try the TS twin first.
JS_TO_TS = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}
PROTOCOL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
NODE_BUILTINS = frozenset("""assert async_hooks buffer child_process cluster console constants crypto dgram diagnostics_channel
dns domain events fs http http2 https inspector module net os path perf_hooks process punycode querystring readline
repl stream string_decoder sys timers tls trace_events tty url util v8 vm wasi worker_threads zlib""".split())
MAX_EXTENDS_DEPTH = 5


def _norm(path: str) -> str:
    p = posixpath.normpath(path)
    return "" if p == "." else p


def package_name(spec: str) -> tuple[str, str]:
    """'@a/b/c' -> ('@a/b', 'c'); 'x/y' -> ('x', 'y'); 'x' -> ('x', '')."""
    parts = spec.split("/")
    n = 2 if spec.startswith("@") else 1
    return "/".join(parts[:n]), "/".join(parts[n:])


class JsResolver:
    def __init__(self, files: set[str], read_text: Callable[[str], str | None]):
        self.files = files
        self.read_text = read_text
        self._cfg_cache: dict[str, dict | None] = {}
        self.workspaces = self._load_workspaces()

    # ---- file lookup ---------------------------------------------------------
    def file_candidates(self, base: str) -> str | None:
        """base is repo-relative, with or without extension; or a directory with an index file."""
        if base in self.files:
            return base
        ext = posixpath.splitext(base)[1]
        if ext in JS_TO_TS:
            stem = base[: -len(ext)]
            for twin in JS_TO_TS[ext]:
                if stem + twin in self.files:
                    return stem + twin
        for e in TS_FIRST:
            if base + e in self.files:
                return base + e
        for e in TS_FIRST:
            idx = posixpath.join(base, "index" + e)
            if idx in self.files:
                return idx
        return None

    # ---- tsconfig / jsconfig -------------------------------------------------
    def _load_config(self, path: str, depth: int = 0) -> dict | None:
        """Effective {'base_url': dir|None, 'paths': {...}, 'paths_base': dir} (extends followed)."""
        if path in self._cfg_cache:
            return self._cfg_cache[path]
        self._cfg_cache[path] = None  # cycle guard
        text = self.read_text(path) if path in self.files else None
        data = parse_jsonc(text) if text is not None else None
        if not isinstance(data, dict):
            return None
        cfg_dir = posixpath.dirname(path)
        result = {"base_url": None, "paths": {}, "paths_base": cfg_dir}

        exts = data.get("extends")
        for ext in ([exts] if isinstance(exts, str) else exts if isinstance(exts, list) else []):
            if isinstance(ext, str) and ext.startswith(".") and depth < MAX_EXTENDS_DEPTH:
                parent = _norm(posixpath.join(cfg_dir, ext))
                for cand in (parent, parent + ".json"):
                    if cand in self.files:
                        pc = self._load_config(cand, depth + 1)
                        if pc:
                            result.update({k: pc[k] for k in ("base_url", "paths", "paths_base")})
                        break

        co = data.get("compilerOptions") or {}
        if isinstance(co.get("baseUrl"), str):
            result["base_url"] = _norm(posixpath.join(cfg_dir, co["baseUrl"]))
            result["paths_base"] = result["base_url"]
        if isinstance(co.get("paths"), dict):
            result["paths"] = {k: v for k, v in co["paths"].items() if isinstance(v, list)}
            result["paths_base"] = result["base_url"] if result["base_url"] is not None else cfg_dir
        result["references"] = [
            r["path"] for r in data.get("references", []) if isinstance(r, dict) and isinstance(r.get("path"), str)
        ]
        self._cfg_cache[path] = result
        return result

    def _config_for(self, from_path: str) -> dict | None:
        d = posixpath.dirname(from_path)
        while True:
            for name in ("tsconfig.json", "jsconfig.json"):
                cfg_path = posixpath.join(d, name) if d else name
                if cfg_path in self.files:
                    cfg = self._load_config(cfg_path)
                    if cfg and (cfg["paths"] or cfg["base_url"] is not None):
                        return cfg
                    # Vite-style solution config: root tsconfig only "references" the real ones.
                    for ref in (cfg or {}).get("references", []):
                        ref_path = _norm(posixpath.join(d, ref))
                        for cand in (ref_path, posixpath.join(ref_path, "tsconfig.json")):
                            rc = self._load_config(cand) if cand in self.files else None
                            if rc and (rc["paths"] or rc["base_url"] is not None):
                                return rc
                    return cfg
            if not d:
                return None
            d = posixpath.dirname(d)

    @staticmethod
    def _match_alias(spec: str, paths: dict) -> tuple[list[str], str] | None:
        """Pick the best `paths` pattern (exact wins, else longest prefix, like TypeScript)."""
        if spec in paths:
            return paths[spec], ""
        best, best_len = None, -1
        for pattern, targets in paths.items():
            if "*" not in pattern:
                continue
            prefix, suffix = pattern.split("*", 1)
            if spec.startswith(prefix) and spec.endswith(suffix) and len(spec) >= len(prefix) + len(suffix):
                if len(prefix) > best_len:
                    best, best_len = (targets, spec[len(prefix): len(spec) - len(suffix)]), len(prefix)
        return best

    # ---- monorepo workspaces ---------------------------------------------------
    def _load_workspaces(self) -> dict[str, tuple[str, dict]]:
        import json
        out: dict[str, tuple[str, dict]] = {}
        for p in sorted(self.files):
            if posixpath.basename(p) != "package.json" or posixpath.dirname(p) == "":
                continue
            text = self.read_text(p)
            try:
                data = json.loads(text) if text else None
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                out.setdefault(data["name"], (posixpath.dirname(p), data))
        return out

    def _resolve_workspace(self, name: str, sub: str) -> str | None:
        pkg_dir, data = self.workspaces[name]
        if sub:
            for base in (posixpath.join(pkg_dir, sub), posixpath.join(pkg_dir, "src", sub)):
                if hit := self.file_candidates(_norm(base)):
                    return hit
            return None
        for field_name in ("source", "module", "main", "types", "typings"):
            val = data.get(field_name)
            if isinstance(val, str) and (hit := self.file_candidates(_norm(posixpath.join(pkg_dir, val)))):
                return hit
        for base in (posixpath.join(pkg_dir, "src", "index"), posixpath.join(pkg_dir, "index")):
            if hit := self.file_candidates(_norm(base)):
                return hit
        return None

    # ---- main entry ------------------------------------------------------------
    def resolve(self, from_path: str, spec: str) -> Resolution:
        if not spec:
            return Resolution("unresolved", reason="empty specifier")

        if spec in (".", "..") or spec.startswith(("./", "../")):
            rel = _norm(posixpath.join(posixpath.dirname(from_path), spec))
            if rel == ".." or rel.startswith("../"):
                return Resolution("unresolved", reason="relative path escapes the repository")
            hit = self.file_candidates(rel)
            return Resolution("internal", [hit]) if hit else Resolution(
                "unresolved", reason=f"no file matches {rel} (tried extensions and index files)")

        if spec.startswith("/"):
            return Resolution("unresolved", reason="absolute filesystem path")
        if spec.startswith("#"):
            return Resolution("unresolved", reason="package.json 'imports' (#) not supported")
        if PROTOCOL.match(spec):
            return Resolution("external", package=spec.split(":", 1)[0] + ":" if not spec.startswith("node:") else spec)

        cfg = self._config_for(from_path)
        if cfg:
            matched = self._match_alias(spec, cfg["paths"])
            if matched:
                targets, captured = matched
                for t in targets:
                    base = _norm(posixpath.join(cfg["paths_base"], t.replace("*", captured)))
                    if hit := self.file_candidates(base):
                        return Resolution("internal", [hit])
                return Resolution("unresolved", reason=f"tsconfig path alias matched but no file found for {spec}")
            if cfg["base_url"] is not None:
                if hit := self.file_candidates(_norm(posixpath.join(cfg["base_url"], spec))):
                    return Resolution("internal", [hit])

        name, sub = package_name(spec)
        if name in self.workspaces:
            hit = self._resolve_workspace(name, sub)
            return Resolution("internal", [hit]) if hit else Resolution(
                "unresolved", reason=f"workspace package {name}: entry not found")
        if name in NODE_BUILTINS:
            return Resolution("external", package=name, reason="node builtin")
        return Resolution("external", package=name)
