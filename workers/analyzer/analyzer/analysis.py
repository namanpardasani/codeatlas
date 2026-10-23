"""Analyse one checkout, fully or incrementally.

full         : parse / chunk everything, replace every derived table.
incremental  : diff the checkout against what the previous analysis stored (content hashes), then
                 - parse + chunk only added and modified files; renamed files keep their rows (and parse results) and are
                   re-chunked only because the path is part of every chunk header;
                 - deleted files are removed (their rows, symbols, imports, chunks, tokens go with them);
                 - unchanged files keep their parse results, tokens, chunks, file contents and vectors;
                 - the GLOBAL stages are recomputed from the union of fresh and reused data, because a changed file can
                   change other files' results: import resolution (an added file can resolve someone else's import), the
                   dependency graph and cycles, duplicate detection, hotspot scores (percentiles are repo-wide), git stats.
The result must be identical to a fresh full analysis of the same tree (tests/test_incremental_equivalence.py).
"""
import logging
import posixpath
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from . import config, db, gitstats
from .blast.callgraph import build_call_graph
from .blast.cochange import build_cochange
from .blast.history import read_history, shallow_boundary
from .chunking import is_indexable
from .docs.facts import extract_facts
from .duplication import find_duplicates
from .embeddings import Embedder
from .graph.edges import edges_from_resolutions
from .graph.metrics import analyze
from .hotspots import HotspotConfig, RepoContext, map_tests, score_all, score_file
from .hotspots.inputs import build_inputs
from .incremental import Diff, classify
from .indexing import IndexStats, SourceFile, index_repo
from .inventory import build_inventory
from .parsing import supported
from .parsing.runner import SandboxedParser
from .parsing.types import ParseResult
from .resolve import resolve_imports, summarize
from .resolve.types import ImportItem

log = logging.getLogger("analyzer.analysis")

# Bump when parsing / chunking / storage semantics change: previous results are then not trusted and the next
# analysis runs in full.
PIPELINE_VERSION = 10  # 9: body_hash + co-change rules; 10: call sites, bindings, call graph (Blast Radius 0-1)

Progress = Callable[[str, int], None]


class Timer:
    def __init__(self) -> None:
        self.ms: dict[str, int] = {}

    @contextmanager
    def __call__(self, stage: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.ms[stage] = self.ms.get(stage, 0) + int((time.perf_counter() - t0) * 1000)


@dataclass
class AnalysisResult:
    mode: str                                   # full | incremental
    sha: str
    files_total: int
    files_reused: int
    diff: dict[str, int] = field(default_factory=dict)
    timings: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    reason: str = ""                            # why this mode
    imports: dict[str, int] = field(default_factory=dict)
    graph_nodes: int = 0
    cycles: int = 0
    duplicate_groups: int = 0
    history_commits: int = 0
    index: IndexStats | None = None
    parse_problems: int = 0

    @property
    def files_changed(self) -> int:
        return self.diff.get("added", 0) + self.diff.get("modified", 0) + self.diff.get("renamed", 0)


def parse_files(root: Path, paths: list[str], file_ids: dict[str, int], progress: Progress) -> dict[int, ParseResult]:
    """Parse the given supported files (each in the sandbox); one bad file never fails the job."""
    results: dict[int, ParseResult] = {}
    step = max(1, len(paths) // 20)
    root = root.resolve()
    if not paths:
        return results
    with SandboxedParser() as parser:
        for n, path in enumerate(paths, 1):
            fid = file_ids[path]
            full = (root / path).resolve()
            if not full.is_relative_to(root):  # inventory never yields these; belt and braces
                results[fid] = ParseResult(status="failed", error="path escapes repo")
                continue
            try:
                source = full.read_bytes()
            except OSError as e:
                results[fid] = ParseResult(status="failed", error=f"read error: {e}"[:300])
                continue
            results[fid] = parser.parse(path, source)
            if n % step == 0:
                progress("parsing", 50 + int(28 * n / len(paths)))
    return results


def _reader(root: Path) -> Callable[[str], str | None]:
    root = root.resolve()

    def read_text(path: str) -> str | None:  # tsconfig / package.json contents
        full = (root / path).resolve()
        if not full.is_relative_to(root):
            return None
        try:
            return full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return read_text


def load_sources(root: Path, records, by_path: dict) -> list[SourceFile]:
    """Text + symbols of the indexable files among `records`, read safely from the checkout."""
    root = root.resolve()
    out: list[SourceFile] = []
    for rec in records:
        if not is_indexable(rec.path, rec.language, rec.size):
            continue
        full = (root / rec.path).resolve()
        if not full.is_relative_to(root):
            continue
        try:
            text = full.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        res = by_path.get(rec.path)
        out.append(SourceFile(rec.path, rec.language, rec.size, text, res.symbols if res else []))
    return out


def _ext(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


def cochange_for(root: Path, tracked: set[str]):
    """Directional co-change rules from the fetched history (bounded by HISTORY_MAX_COMMITS). The shallow-clone
    boundary commit is excluded: against 'nothing' it appears to add every file at once."""
    try:
        commits = read_history(root, "HEAD", max_commits=config.HISTORY_MAX_COMMITS)
    except Exception as e:  # noqa: BLE001  history is optional: no rules is a valid (empty) model
        log.warning("co-change history unavailable: %s", type(e).__name__)
        commits = []
    return build_cochange(commits, tracked=tracked, max_files=config.COCHANGE_RULE_MAX_FILES,
                          exclude=shallow_boundary(root))


def decide(requested_mode: str, previous_ready: bool, previous_version: int | None, has_files: bool) -> tuple[str, str]:
    """(mode, reason). Incremental only when the previous analysis is complete, current and trustworthy."""
    if requested_mode == "full":
        return "full", "full re-analysis requested"
    if not has_files:
        return "full", "first analysis of this repo"
    if not previous_ready:
        return "full", "the previous analysis did not complete"
    if previous_version != PIPELINE_VERSION:
        return "full", f"pipeline version changed ({previous_version} -> {PIPELINE_VERSION})"
    return "incremental", "previous analysis is complete and current"


def analyze_checkout(conn, repo_id: int, job_id: int, root: Path, sha: str, *, progress: Progress,
                     embedder: Embedder | None, requested_mode: str = "auto", previous_ready: bool = False,
                     previous_version: int | None = None) -> AnalysisResult:
    started = time.perf_counter()
    timer = Timer()

    progress("inventory", 30)
    with timer("inventory"):
        records = build_inventory(root)
    rec_by_path = {f.path: f for f in records}
    new_hashes = {f.path: f.content_hash for f in records}

    prev_state = db.load_file_state(conn, repo_id)
    mode, reason = decide(requested_mode, previous_ready, previous_version, bool(prev_state))
    incremental = mode == "incremental"

    diff = Diff()
    renames: list[tuple[str, str]] = []
    if incremental:
        with timer("diff"):
            diff = classify({p: h for p, (_, h) in prev_state.items()}, new_hashes)
            # a move that changes the extension may change the parser (a.js -> a.ts): treat it as delete + add
            renames = [(o, n) for o, n in diff.renamed if _ext(o) == _ext(n)]
            for o, n in diff.renamed:
                if _ext(o) != _ext(n):
                    diff.deleted.append(o)
                    diff.added.append(n)
            diff.renamed = renames
            diff.deleted.sort()
            diff.added.sort()
        changed = diff.changed_count
        progress(f"incremental: {changed} changed, {len(diff.unchanged)} reused, {len(diff.deleted)} removed", 40)
        log.info("incremental: %s", diff.summary())
    else:
        progress(f"full analysis: {len(records)} files ({reason})", 40)

    progress("saving", 45)
    with timer("saving"):
        file_ids = db.save_files(conn, repo_id, sha, records, renames=renames or None)
    path_of = {fid: p for p, fid in file_ids.items()}

    # ---- parse: only what is new (everything on a full run) ------------------------------------------------
    if incremental:
        parse_paths = {p for p in diff.reparse if supported(p)}
        # self-healing: a supported file the previous run left without parse results is parsed now
        parse_paths |= {path for (path,) in conn.execute(
            "SELECT path FROM files WHERE repo_id = %s AND parse_status IS NULL", (repo_id,)) if supported(path)}
        chunk_paths: set[str] | None = set(diff.rechunk) | parse_paths
    else:
        parse_paths = {f.path for f in records if supported(f.path)}
        chunk_paths = None

    progress("parsing", 50)
    with timer("parsing"):
        results = parse_files(root, sorted(parse_paths), file_ids, progress)
        db.save_parse_results(conn, repo_id, results, replace_all=not incremental)
        db.save_tokens(conn, results)
    fresh_ids = set(results)
    reused_ids = [fid for fid in file_ids.values() if fid not in fresh_ids]

    # ---- resolve imports against the CURRENT file set (an added/removed file changes other files' results) ----
    progress("resolving", 80)
    with timer("resolving"):
        items = [ImportItem(path_of[fid], i, im.specifier, im.kind, im.names, im.level)
                 for fid, res in results.items() for i, im in enumerate(res.imports)]
        if incremental:
            items += db.load_import_items(conn, repo_id, fresh_ids)
        resolutions = resolve_imports(set(file_ids), items, _reader(root))
        db.save_resolutions(conn, repo_id, file_ids, resolutions)
        counts = summarize(resolutions)

    by_path: dict[str, ParseResult] = {path_of[fid]: res for fid, res in results.items()}
    if incremental:
        reused = db.load_parse_summaries(conn, repo_id, reused_ids)
        db.load_call_inputs(conn, repo_id, reused)
        by_path.update(reused)

    progress("call graph", 81)
    with timer("callgraph"):
        calls = build_call_graph({p: r for p, r in by_path.items() if supported(p)}, resolutions)
        db.save_call_graph(conn, repo_id, job_id, file_ids, calls)

    progress("graph", 82)
    with timer("graph"):
        code_files = {f.path for f in records if supported(f.path)}
        edges = edges_from_resolutions(resolutions, code_files)
        analysis = analyze(sorted(code_files), edges)
        db.save_graph(conn, repo_id, file_ids, analysis, edges)

    progress("git history", 84)
    with timer("git"):
        git = gitstats.collect(root, tracked=set(file_ids))
        db.save_git_stats(conn, repo_id, job_id, file_ids, git)
        db.save_cochange_rules(conn, repo_id, job_id, file_ids, cochange_for(root, set(file_ids)))

    progress("duplication", 86)
    with timer("duplication"):
        tokens = {p: (x.token_hashes, x.token_lines) for p, x in by_path.items() if file_ids[p] in fresh_ids}
        if incremental:
            tokens.update(db.load_tokens(conn, repo_id, fresh_ids))
        dups = find_duplicates(tokens)
        db.save_duplicates(conn, repo_id, file_ids, {p: (x.metrics.lines if x.metrics else 0) for p, x in by_path.items()}, dups)

    progress("hotspots", 88)
    with timer("hotspots"):
        tests = map_tests([f.path for f in records if f.path in by_path and not f.is_test],
                          [f.path for f in records if f.is_test])
        hs_inputs = build_inputs(records, by_path, analysis, git, dups, tests)
        hs_config = HotspotConfig.from_env()
        hs_ctx = RepoContext.build(hs_inputs, history_available=git.commits_seen > 0, window_days=git.window_days)
        scored = score_all(hs_inputs, hs_ctx, hs_config, score_file)
        db.save_hotspots(conn, repo_id, job_id, file_ids, scored, hs_config)

    with timer("facts"):
        db.save_repo_facts(conn, repo_id, extract_facts(root, records, by_path))

    # ---- chunks + vectors: only changed files on an incremental run (unchanged text hits the embedding cache) ----
    progress("chunking", 90)
    with timer("chunking"):
        todo = records if chunk_paths is None else [rec_by_path[p] for p in sorted(chunk_paths) if p in rec_by_path]
        sources = load_sources(root, todo, by_path)
        db.save_file_contents(conn, repo_id, file_ids, sources, replace_all=chunk_paths is None, refresh_paths=chunk_paths)
    with timer("embedding"):
        index = index_repo(conn, embedder, repo_id, file_ids, sources, refresh_paths=chunk_paths,
                           on_progress=lambda f: progress("embedding", 91 + int(8 * f)))
        db.save_index_stats(conn, job_id, index)

    db.set_pipeline_version(conn, repo_id, PIPELINE_VERSION)
    duration_ms = int((time.perf_counter() - started) * 1000)
    reused = len(diff.unchanged) if incremental else 0
    result = AnalysisResult(
        mode=mode, sha=sha, files_total=len(records), files_reused=reused, diff=diff.summary() if incremental else {},
        timings=timer.ms, duration_ms=duration_ms, reason=reason, imports=counts, graph_nodes=len(analysis.graph.nodes),
        cycles=len(analysis.cycles), duplicate_groups=len(dups.groups), history_commits=git.commits_seen, index=index,
        parse_problems=sum(1 for x in results.values() if x.status in ("failed", "partial")))
    if not incremental:
        result.diff = {"added": len(records), "modified": 0, "deleted": 0, "renamed": 0, "unchanged": 0}
    return result
