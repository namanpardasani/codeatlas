"""Facts about a repo read LITERALLY from its files (no LLM, nothing invented): language mix, entry points, how to run,
README excerpt. They feed the repo overview page and ground the overview summary."""
import json
import posixpath
import re
import tomllib
from collections import Counter
from pathlib import Path

MAX_READ = 200_000
CONVENTIONAL = {
    "python": {"__main__.py", "main.py", "app.py", "cli.py", "manage.py", "wsgi.py", "asgi.py", "server.py", "run.py"},
    "typescript": {"index.ts", "main.ts", "app.ts", "server.ts", "cli.ts", "index.tsx", "main.tsx"},
    "javascript": {"index.js", "main.js", "app.js", "server.js", "cli.js", "index.mjs"},
}
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
RUN_HEADINGS = re.compile(r"install|usage|getting started|quick ?start|run|build|develop|setup|example", re.I)
MAKE_TARGET = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)")


def _read(root: Path, rel: str, limit: int = MAX_READ) -> str | None:
    full = (root / rel).resolve()
    if not full.is_relative_to(root.resolve()) or not full.is_file():
        return None
    try:
        return full.read_bytes()[:limit].decode("utf-8", errors="replace")
    except OSError:
        return None


def readme_info(root: Path, paths: list[str]) -> dict | None:
    cands = sorted((p for p in paths if posixpath.basename(p).lower().startswith("readme")), key=lambda p: (p.count("/"), p))
    for rel in cands:
        text = _read(root, rel)
        if not text:
            continue
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith(("[![", "![", "<!--", "<p ", "<img", "</", "<a "))]
        body = "\n".join(lines).strip()
        return {"path": rel, "excerpt": re.sub(r"\n{3,}", "\n\n", body)[:1200], "text": text}
    return None


def readme_run_blocks(text: str, limit: int = 3) -> list[dict]:
    """Fenced code blocks under install/usage/run-like headings, copied literally."""
    out, title, in_fence, block = [], "", False, []
    fence_title = ""
    for ln in text.splitlines():
        if ln.lstrip().startswith(("```", "~~~")):
            if in_fence:
                if block and RUN_HEADINGS.search(fence_title):
                    out.append({"source": "README", "title": fence_title, "commands": block[:8]})
                    if len(out) >= limit:
                        return out
                in_fence, block = False, []
            else:
                in_fence, fence_title = True, title
            continue
        if in_fence:
            if ln.strip():
                block.append(ln.rstrip())
        elif (m := HEADING.match(ln)):
            title = m.group(2)
    return out


def extract_facts(root: Path, records, by_path: dict) -> dict:
    """records: FileRecord list; by_path: path -> ParseResult (for conventional-entry filtering only)."""
    paths = sorted(r.path for r in records)
    langs: Counter = Counter()
    lines: Counter = Counter()
    for r in records:
        if r.language in ("python", "typescript", "javascript", "go", "java", "rust", "ruby", "c", "cpp", "csharp"):
            langs[r.language] += 1
            lines[r.language] += r.lines
    facts: dict = {"languages": [{"language": l, "files": langs[l], "lines": lines[l]} for l, _ in langs.most_common()],
                   "entry_points": [], "run_hints": [], "readme": None, "manifests": []}

    entries: dict[str, str] = {}
    for r in records:
        base = posixpath.basename(r.path)
        if r.language in CONVENTIONAL and base in CONVENTIONAL[r.language] and not r.is_test and r.path.count("/") <= 2:
            entries.setdefault(r.path, "conventional entry file name")
        if r.language == "python" and not r.is_test and r.path in by_path:
            text = _read(root, r.path, 100_000)
            if text and re.search(r'^if __name__ == [\'"]__main__[\'"]', text, re.M):
                entries[r.path] = "has an `if __name__ == \"__main__\"` block"

    hints: list[dict] = []
    for rel in paths:
        base = posixpath.basename(rel)
        depth = rel.count("/")
        if base == "package.json" and depth <= 2:
            facts["manifests"].append(rel)
            try:
                pkg = json.loads(_read(root, rel) or "")
            except ValueError:
                continue
            if isinstance(pkg, dict):
                folder = posixpath.dirname(rel)
                for key in ("main", "module"):
                    if isinstance(pkg.get(key), str):
                        entries[posixpath.normpath(posixpath.join(folder, pkg[key]))] = f"`{key}` in {rel}"
                bins = pkg.get("bin")
                for b in ([bins] if isinstance(bins, str) else list((bins or {}).values()) if isinstance(bins, dict) else []):
                    entries[posixpath.normpath(posixpath.join(folder, b))] = f"`bin` in {rel}"
                scripts = pkg.get("scripts")
                if isinstance(scripts, dict):
                    cmds = [f"npm run {k}    # {v}" for k, v in scripts.items() if k in ("start", "dev", "build", "test", "lint", "serve")][:6]
                    if cmds:
                        hints.append({"source": rel, "title": "package.json scripts", "commands": cmds})
        elif base == "pyproject.toml" and depth <= 2:
            facts["manifests"].append(rel)
            try:
                data = tomllib.loads(_read(root, rel) or "")
            except tomllib.TOMLDecodeError:
                continue
            scripts = {**(data.get("project", {}).get("scripts") or {}), **(data.get("tool", {}).get("poetry", {}).get("scripts") or {})}
            for name, target in list(scripts.items())[:6]:
                entries[f"{name} -> {target}"] = f"console script in {rel}"
            if scripts:
                hints.append({"source": rel, "title": "console scripts", "commands": [f"{n}    # {t}" for n, t in list(scripts.items())[:6]]})
        elif base == "Dockerfile" and depth <= 2:
            facts["manifests"].append(rel)
            cmd = [ln.strip() for ln in (_read(root, rel) or "").splitlines() if ln.strip().upper().startswith(("CMD", "ENTRYPOINT"))]
            if cmd:
                hints.append({"source": rel, "title": "container start command", "commands": cmd[:3]})
        elif base in ("Makefile", "makefile") and depth <= 1:
            facts["manifests"].append(rel)
            targets = [m.group(1) for ln in (_read(root, rel) or "").splitlines() if (m := MAKE_TARGET.match(ln)) and not m.group(1).startswith(".")]
            useful = [t for t in targets if t in ("run", "start", "dev", "build", "test", "install", "serve", "lint")][:6]
            if useful:
                hints.append({"source": rel, "title": "make targets", "commands": [f"make {t}" for t in useful]})
        elif base in ("docker-compose.yml", "docker-compose.yaml", "compose.yml") and depth <= 1:
            facts["manifests"].append(rel)
            svc = re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", _read(root, rel) or "", re.M)[:8]
            if svc:
                hints.append({"source": rel, "title": "docker compose services", "commands": ["docker compose up    # services: " + ", ".join(svc)]})

    readme = readme_info(root, paths)
    if readme:
        facts["readme"] = {"path": readme["path"], "excerpt": readme["excerpt"]}
        hints += readme_run_blocks(readme["text"])
    facts["entry_points"] = [{"path": p, "why": why} for p, why in sorted(entries.items())][:12]
    facts["run_hints"] = hints[:8]
    facts["manifests"] = sorted(set(facts["manifests"]))[:12]
    return facts
