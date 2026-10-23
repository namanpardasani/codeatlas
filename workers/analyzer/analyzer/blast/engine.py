"""One call from a change to its blast radius, for a repo on disk (offline evaluation, PR analysis in the worker).

Everything is computed from the BASE of the change: the snapshot, the call graph and the co-change model all describe
the code and history as they were before the change, so nothing that happened later can leak into the prediction.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path

from .callgraph import CallGraph, build_call_graph
from .changes import ChangeSet
from .cochange import CoChangeModel, build_cochange
from .history import read_history, shallow_boundary
from .impact import ImpactGraph, ImpactResult, Params, apply_change_paths, propagate, seeds_from
from .inputs import EMPTY_TREE, ResolvedChange, commit_change
from .snapshot import ParseCache, Snapshot, build_snapshot
from .source import GitSource
from .testsel import TestSelection, select_tests
from .history import Commit
from .reviewers import Reviewer, suggest_reviewers
from .risk import GraphFacts, RiskResult, risk

HISTORY_COMMITS = 500


@dataclass
class BaseModel:
    sha: str
    snapshot: Snapshot
    calls: CallGraph
    cochange: CoChangeModel
    history: list[Commit] = field(default_factory=list, repr=False)
    _graphs: dict = field(default_factory=dict, repr=False)
    _facts: GraphFacts | None = field(default=None, repr=False)

    @property
    def facts(self) -> GraphFacts:
        if self._facts is None:
            self._facts = GraphFacts(self.snapshot)
        return self._facts

    def graph(self, params: Params) -> ImpactGraph:
        """The impact graph depends only on the base and the edge switches/weights, not on the change: build it once
        and reuse it for every PR / commit analysed against this base."""
        if params not in self._graphs:
            self._graphs[params] = ImpactGraph(self.calls, self.snapshot.importers_of, self.cochange, params)
        return self._graphs[params]


@dataclass
class BlastReport:
    change: ResolvedChange
    base: BaseModel | None
    impact: ImpactResult | None
    timings_ms: dict[str, int] = field(default_factory=dict)
    tests: TestSelection | None = None
    risk: RiskResult | None = None
    reviewers: list[Reviewer] = field(default_factory=list)

    @property
    def changes(self) -> ChangeSet:
        return self.change.changes


def base_model(repo: Path, sha: str, *, parser=None, cache: ParseCache | None = None,
               history_commits: int = HISTORY_COMMITS, timings: dict | None = None) -> BaseModel:
    t = timings if timings is not None else {}
    t0 = time.perf_counter()
    snap = build_snapshot(GitSource(repo, sha), parser=parser, cache=cache)
    t["snapshot"] = int((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    calls = build_call_graph(snap.parsed, snap.resolutions)
    t["callgraph"] = int((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    commits = read_history(repo, sha, max_commits=history_commits)          # history up to and including the base
    cc = build_cochange(commits, tracked=set(snap.files), exclude=shallow_boundary(repo))
    t["cochange"] = int((time.perf_counter() - t0) * 1000)
    return BaseModel(sha, snap, calls, cc, commits)


def commit_author(repo: Path, sha: str) -> tuple[str | None, int]:
    """(author email, author time) of a commit, for the inexperience feature and reviewer exclusion."""
    import subprocess
    out = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%ae%x01%at", "--end-of-options", sha],
                         capture_output=True, text=True)
    if out.returncode != 0 or "\x01" not in out.stdout:
        return None, int(time.time())
    email, at = out.stdout.strip().split("\x01")
    return email.strip().lower() or None, int(at)


def analyze_commit(repo: Path, rev: str, *, params: Params = Params(tiered=True), parser=None, cache: ParseCache | None = None,
                   base: BaseModel | None = None, risk_model=None) -> BlastReport:
    t: dict[str, int] = {}
    t0 = time.perf_counter()
    change = commit_change(repo, rev, parser=parser)
    t["changes"] = int((time.perf_counter() - t0) * 1000)
    if change.base == EMPTY_TREE:
        return BlastReport(change, None, None, t)                          # first commit: nothing existed to break
    model = base if base is not None and base.sha == change.base else base_model(repo, change.base, parser=parser,
                                                                                    cache=cache, timings=t)
    t0 = time.perf_counter()
    impact = apply_change_paths(propagate(model.graph(params), seeds_from(change.changes, model.calls)), change.changes)
    t["propagate"] = int((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    tests = select_tests(model.snapshot, model.calls, change.changes, impact)
    t["tests"] = int((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    author, when = commit_author(repo, change.head)
    rk = risk(change.changes, impact, model.calls, model.cochange, model.history, model.facts, tests, author,
              model.snapshot, model=risk_model)
    revs = suggest_reviewers(impact, model.history, when, exclude_email=author)
    t["risk"] = int((time.perf_counter() - t0) * 1000)
    return BlastReport(change, model, impact, t, tests, rk, revs)
