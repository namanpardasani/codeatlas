"""Bottom-up documentation: symbols -> files -> folders -> repo overview.

Every target has an INPUT HASH covering everything its summary depends on (a Merkle tree):
  symbol  = its source text, name, kind, signature, path
  file    = its content hash + the hashes of its documented symbols
  folder  = the hashes of the files and sub-folders inside it
  repo    = the hashes of top-level folders/files + the README/facts
so a change invalidates only the chain from the changed file up to the root, never the rest.

A summary is reused when (input hash, prompt version, model) matches: first the current doc row, then the shared
`summary_cache` (identical code in another repo or a fork costs nothing). Otherwise a target gets an LLM summary while the
per-job call budget lasts (repo overview first, then folders, important files, complex symbols) and a deterministic
EXTRACTIVE summary afterwards or when the LLM is unavailable/unreliable: the job always finishes."""
import hashlib
import logging
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from psycopg.types.json import Jsonb

from .. import config
from ..llm import LLMError, Message
from ..llm.types import Delta, Usage
from . import extractive
from .guard import check_entry_points, check_summary
from .prompts import build

log = logging.getLogger("analyzer.docs")
TYPE_RANK = {"repo": 0, "folder": 1, "file": 2, "symbol": 3}          # who gets the LLM budget first
BOTTOM_UP = {"symbol": 0, "file": 1, "folder": 2, "repo": 3}          # the order summaries are produced in


def _h(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf8", errors="replace")).hexdigest()


@dataclass
class Target:
    type: str
    ref: str
    path: str
    hash: str = ""
    extractive: str = ""
    depth: int = 0
    importance: float = 0.0
    children: list[tuple[str, str]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.type, self.ref)


@dataclass
class DocsStats:
    targets: int = 0
    llm_calls: int = 0
    reused: int = 0          # unchanged since the last run (same input hash, still an LLM summary)
    cached: int = 0          # served from the shared summary cache
    extractive: int = 0      # ended up with a deterministic summary
    guard_rejected: int = 0  # LLM output thrown away by the guard
    llm_errors: int = 0
    budget: int = 0
    budget_exhausted: bool = False
    llm_disabled_reason: str | None = None
    model: str | None = None


# ---- material ---------------------------------------------------------------------------------------------
def _module_doc(head: str, language: str | None) -> str:
    if language == "python":
        m = re.match(r'\s*(?:#[^\n]*\n\s*)*[rRuU]?("""|\'\'\')(.+?)\1', head, re.S)
        return re.sub(r"\s+", " ", m.group(2)).strip() if m else ""
    m = re.match(r"\s*/\*\*?(.+?)\*/", head, re.S)
    return re.sub(r"\s*\*\s*", " ", m.group(1)).strip() if m else ""


def _qualified(name: str, parent: str | None) -> str:
    return f"{parent}.{name}" if parent else name


def select_symbols(symbols: list[tuple]) -> list[tuple]:
    """Which symbols of ONE file get their own summary: classes, and complex or long functions/methods (local rule, so a
    file's selection never depends on other files). symbols rows: (name, kind, parent, start, end, params, complexity, signature)"""
    picked = [s for s in symbols if s[1] == "class" or (s[1] in ("function", "method") and
              ((s[6] or 0) >= config.DOCS_MIN_SYMBOL_COMPLEXITY or (s[4] - s[3] + 1) >= 40))]
    picked.sort(key=lambda s: (s[1] != "class", -(s[6] or 0), -(s[4] - s[3]), s[0]))
    return picked[:config.DOCS_MAX_SYMBOLS_PER_FILE]


def build_targets(conn, repo_id: int, facts: dict) -> tuple[list[Target], dict]:
    repo_name = conn.execute("SELECT full_name FROM repos WHERE id = %s", (repo_id,)).fetchone()[0]
    files = conn.execute(
        """SELECT id, path, language, content_hash, lines, hotspot_score, pagerank, fan_in FROM files
           WHERE repo_id = %s AND module IS NOT NULL ORDER BY path""", (repo_id,)).fetchall()
    ids = [f[0] for f in files]
    syms: dict[int, list[tuple]] = {}
    for fid, name, kind, parent, start, end, params, cx, sig in conn.execute(
            """SELECT file_id, name, kind, parent_name, start_line, end_line, params, complexity, signature
               FROM symbols WHERE repo_id = %s AND file_id = ANY(%s) ORDER BY file_id, idx""", (repo_id, ids)):
        syms.setdefault(fid, []).append((name, kind, parent, start, end, list(params or []), cx, sig))
    imports: dict[str, list[str]] = {}
    for a, b in conn.execute("""SELECT a.path, b.path FROM dependencies d JOIN files a ON a.id = d.from_file_id
                                JOIN files b ON b.id = d.to_file_id WHERE d.repo_id = %s ORDER BY 1, 2""", (repo_id,)):
        imports.setdefault(a, []).append(b)

    targets: dict[tuple, Target] = {}
    material: dict[str, dict] = {}
    for i in range(0, len(files), 100):                                    # batches: never hold every file's text at once
        batch = files[i:i + 100]
        texts = dict(conn.execute("SELECT f.path, left(c.content, 60000) FROM file_contents c JOIN files f ON f.id = c.file_id "
                                  "WHERE f.id = ANY(%s)", ([f[0] for f in batch],)).fetchall())
        for fid, path, language, chash, lines_n, hot, pr, fan_in in batch:
            text = texts.get(path, "")
            lines = text.split("\n")
            head = text[:config.DOCS_CODE_CHARS]
            picks = select_symbols(syms.get(fid, []))
            sym_info = {}
            for name, kind, parent, start, end, params, cx, sig in picks:
                q = _qualified(name, parent)
                src = "\n".join(lines[start - 1:end])[:config.DOCS_CODE_CHARS]
                doc = extractive.symbol_doc(lines, start, end, language)
                t = Target("symbol", f"{path}::{q}", path, _h("sym", config.DOCS_PROMPT_VERSION, path, q, kind, sig, _h(src)),
                           extractive.symbol_summary(path, q, kind, start, end, params, doc),
                           importance=float(cx or 0), meta={"qualified": q, "kind": kind, "code": src, "language": language})
                targets[t.key] = t
                sym_info[q] = t.key
            ft = Target("file", path, path, extractive=extractive.file_summary(
                path, language, lines_n, [(_qualified(s[0], s[2]), s[1]) for s in syms.get(fid, []) if s[1] in ("class", "function", "method")][:30],
                imports.get(path, []), fan_in or 0, _module_doc(head, language)),
                importance=float(hot or 0) * 10 + float(pr or 0) * 1000 + (fan_in or 0) + lines_n / 1000,
                children=list(sym_info.values()), meta={"language": language, "lines": lines_n, "head": head, "imports": imports.get(path, []),
                                                        "chash": chash, "symbols": [(s[0], s[1], s[2], s[3], s[4], s[7]) for s in syms.get(fid, [])]})
            targets[ft.key] = ft
            material[path] = {"fid": fid}

    # folders and the repo root
    folders: set[str] = set()
    for f in files:
        d = posixpath.dirname(f[1])
        while d:
            folders.add(d)
            d = posixpath.dirname(d)
    for d in sorted(folders, key=lambda x: (-x.count("/"), x)):
        subs = sorted(x for x in folders if posixpath.dirname(x) == d)
        direct = sorted(f[1] for f in files if posixpath.dirname(f[1]) == d)
        ft = Target("folder", d, d, depth=d.count("/") + 1, importance=float(len(direct)),
                    children=[("file", p) for p in direct] + [("folder", s) for s in subs],
                    extractive=extractive.folder_summary(d, [(p, "") for p in direct], subs), meta={"files": direct, "subfolders": subs})
        targets[ft.key] = ft
    top_dirs = sorted(x for x in folders if "/" not in x)
    top_files = sorted(f[1] for f in files if "/" not in f[1])
    repo_t = Target("repo", "", "", children=[("folder", d) for d in top_dirs] + [("file", p) for p in top_files],
                    extractive=extractive.repo_summary(repo_name, (facts.get("readme") or {}).get("excerpt", ""),
                                                       facts.get("languages", []), facts.get("entry_points", [])),
                    meta={"name": repo_name})
    targets[repo_t.key] = repo_t

    # Merkle hashes, children before parents
    def digest(t: Target) -> str:
        if t.hash:
            return t.hash
        kids = sorted((k[1], digest(targets[k])) for k in t.children if k in targets)
        if t.type == "file":
            t.hash = _h("file", config.DOCS_PROMPT_VERSION, t.path, t.meta["chash"], *[h for _, h in kids])
        elif t.type == "folder":
            t.hash = _h("folder", config.DOCS_PROMPT_VERSION, t.path, *[f"{r}={h}" for r, h in kids])
        else:
            t.hash = _h("repo", config.DOCS_PROMPT_VERSION, t.meta["name"], *[f"{r}={h}" for r, h in kids],
                        _h((facts.get("readme") or {}).get("excerpt", "")), _h(repr(facts.get("entry_points")), repr(facts.get("languages"))))
        return t.hash
    for t in targets.values():
        digest(t)
    return list(targets.values()), {"repo_name": repo_name, "known_paths": {f[1] for f in files}}


# ---- prompts per level -----------------------------------------------------------------------------------
def _short(s: str, n: int = 240) -> str:
    return extractive.first_sentence(s, n) or s[:n]


def prompt_for(t: Target, current: dict, by_key: dict, facts: dict) -> tuple[list[Message], str]:
    if t.type == "symbol":
        header = f"KIND: {t.meta['kind']}\nFILE: {t.path}\nNAME: {t.meta['qualified']}"
        return build("symbol", header, t.meta["code"])
    if t.type == "file":
        parts = [f"PATH: {t.path} ({t.meta['language']}, {t.meta['lines']} lines)"]
        if t.meta["imports"]:
            parts.append("IMPORTS (files in this repo): " + ", ".join(t.meta["imports"][:10]))
        defs = []
        for name, kind, parent, start, end, sig in t.meta["symbols"][:30]:
            q = _qualified(name, parent)
            key = ("symbol", f"{t.path}::{q}")
            line = f"- `{q}` ({kind}, lines {start}-{end}): " + (_short(current[key][0]) if key in current else sig[:160])
            defs.append(line)
        if defs:
            parts.append("DEFINES:\n" + "\n".join(defs))
        parts.append("CODE (start of file):\n" + t.meta["head"])
        return build("file", f"FILE: {t.path}", "\n\n".join(parts))
    if t.type == "folder":
        lines = [f"- `{k[1]}`: {_short(current[k][0])}" for k in t.children if k in current]
        return build("folder", f"FOLDER: {t.path}/", "CONTENTS:\n" + "\n".join(lines))
    parts = [f"REPOSITORY: {t.meta['name']}"]
    if facts.get("languages"):
        parts.append("LANGUAGES: " + ", ".join(f"{l['language']} ({l['files']} files)" for l in facts["languages"][:5]))
    if facts.get("entry_points"):
        parts.append("ENTRY POINTS:\n" + "\n".join(f"- `{e['path']}` ({e['why']})" for e in facts["entry_points"][:8]))
    if (facts.get("readme") or {}).get("excerpt"):
        parts.append("README EXCERPT:\n" + facts["readme"]["excerpt"][:900])
    mods = [f"- `{k[1]}`: {_short(current[k][0])}" for k in t.children if k in current]
    if mods:
        parts.append("TOP-LEVEL PARTS:\n" + "\n".join(mods[:20]))
    return build("repo", f"REPOSITORY: {t.meta['name']}", "\n\n".join(parts))


def call_llm(llm, messages: list[Message]) -> tuple[str, int, int]:
    text, tin, tout = "", 0, 0
    for ev in llm.stream(messages, max_tokens=230, temperature=0.1):
        if isinstance(ev, Delta):
            text += ev.text
        elif isinstance(ev, Usage):
            tin, tout = ev.input_tokens, ev.output_tokens
    return text, tin, tout


# ---- the run ----------------------------------------------------------------------------------------------
def real_llm(llm):
    """The fake provider cannot write documentation: treat it as 'no LLM'."""
    return None if llm is None or getattr(llm, "name", "") == "fake" else llm


def generate_docs(conn, llm, repo_id: int, sha: str, *, max_calls: int | None = None,
                  on_progress: Callable[[int, int], None] | None = None) -> DocsStats:
    llm = real_llm(llm)
    budget = config.DOCS_MAX_CALLS if max_calls is None else max_calls
    stats = DocsStats(budget=budget, model=llm.model if llm else None)
    facts_row = conn.execute("SELECT facts FROM repo_facts WHERE repo_id = %s", (repo_id,)).fetchone()
    facts = facts_row[0] if facts_row else {}
    targets, ctx = build_targets(conn, repo_id, facts)
    by_key = {t.key: t for t in targets}
    stats.targets = len(targets)
    known_paths: set[str] = ctx["known_paths"]
    version = config.DOCS_PROMPT_VERSION

    existing = {(tt, ref): (h, summary, source, model, pv) for tt, ref, h, summary, source, model, pv in conn.execute(
        "SELECT target_type, target_ref, input_hash, summary, source, model, prompt_version FROM doc_summaries WHERE repo_id = %s", (repo_id,))}
    cache = {}
    if llm:
        cache = {h: s for h, s in conn.execute("SELECT input_hash, summary FROM summary_cache WHERE prompt_version = %s AND model = %s "
                                               "AND input_hash = ANY(%s)", (version, llm.model, [t.hash for t in targets]))}

    current: dict[tuple, tuple[str, str]] = {}      # key -> (summary, source)
    final: dict[tuple, tuple[str, str, str | None]] = {}   # key -> (summary, source, model)
    todo: list[Target] = []
    for t in targets:
        old = existing.get(t.key)
        if old and old[0] == t.hash and old[2] == "llm" and (llm is None or (old[4] == version and old[3] == llm.model)):
            current[t.key] = (old[1], "llm")
            final[t.key] = (old[1], "llm", old[3])
            stats.reused += 1
        elif t.hash in cache:
            current[t.key] = (cache[t.hash], "llm")
            final[t.key] = (cache[t.hash], "llm", llm.model if llm else None)
            stats.cached += 1
        else:
            current[t.key] = (t.extractive, "extractive")          # available to parents' prompts straight away
            todo.append(t)

    # LLM phase: the most valuable targets first while the budget lasts, produced bottom-up
    if llm and todo and budget > 0:
        chosen = sorted(todo, key=lambda t: (TYPE_RANK[t.type], t.depth if t.type == "folder" else 0, -t.importance, t.ref))[:budget]
        stats.budget_exhausted = len(todo) > len(chosen)
        order = sorted(chosen, key=lambda t: (BOTTOM_UP[t.type], -t.depth, t.ref))
        for n, t in enumerate(order, 1):
            if stats.llm_disabled_reason:
                break
            messages, material = prompt_for(t, current, by_key, facts)
            try:
                raw, tin, tout = call_llm(llm, messages)
                stats.llm_calls += 1
            except LLMError as e:           # rate limit / quota / outage: stop calling, finish with extractive summaries
                stats.llm_errors += 1
                stats.llm_disabled_reason = f"{e.kind}: {e.message}"
                log.warning("docs: LLM disabled for the rest of this run (%s)", stats.llm_disabled_reason)
                break
            clean, issues = check_summary(raw, material, known_paths)
            if clean is not None and t.type == "repo":
                clean, more = check_entry_points(clean, facts.get("entry_points", []))
                issues += more
            if clean is None:
                stats.guard_rejected += 1
                log.info("docs: guard rejected the summary of %s %s (%s)", t.type, t.ref or "(repo)", "; ".join(issues[:2]))
            else:
                if t.path and t.type != "repo" and t.path not in clean:
                    clean = f"`{t.path}` — {clean}"
                conn.execute("INSERT INTO summary_cache (input_hash, prompt_version, model, summary, tokens_in, tokens_out) "
                             "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (t.hash, version, llm.model, clean, tin, tout))
                current[t.key] = (clean, "llm")
                final[t.key] = (clean, "llm", llm.model)
            if on_progress:
                on_progress(n, len(order))
    elif todo and budget == 0:
        stats.budget_exhausted = True

    for t in targets:
        if t.key not in final:
            final[t.key] = (t.extractive, "extractive", None)
            stats.extractive += 1

    with conn.transaction():
        with conn.cursor() as cur:
            live = [(t.type, t.ref) for t in targets]
            cur.execute("DELETE FROM doc_summaries WHERE repo_id = %s AND NOT ((target_type, target_ref) IN (SELECT * FROM unnest(%s::text[], %s::text[])))",
                        (repo_id, [k[0] for k in live], [k[1] for k in live]))
            cur.executemany(
                """INSERT INTO doc_summaries (repo_id, target_type, target_ref, input_hash, summary, source, model, prompt_version, commit_sha, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                   ON CONFLICT (repo_id, target_type, target_ref) DO UPDATE SET input_hash = EXCLUDED.input_hash,
                     summary = EXCLUDED.summary, source = EXCLUDED.source, model = EXCLUDED.model,
                     prompt_version = EXCLUDED.prompt_version, commit_sha = EXCLUDED.commit_sha, updated_at = now()""",
                [(repo_id, t.type, t.ref, t.hash, final[t.key][0], final[t.key][1], final[t.key][2], version, sha) for t in targets])
            cur.execute("""UPDATE repos SET docs_status = %s, docs_commit_sha = %s, docs_model = %s, docs_generated_at = now() WHERE id = %s""",
                        ("ready" if stats.extractive == 0 else "partial", sha, stats.model, repo_id))
    return stats
