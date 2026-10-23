"""Impact propagation: from the symbols a change touches to everything that may be affected, ranked and explained.

The impact graph is the dependency graph read BACKWARDS (if B changes, whoever depends on B may break):
  call      caller -> callee in the code   =>  callee impacts caller     weight by confidence (exact > probable > weak)
  import    file A imports file B           =>  B impacts A               (uses that are not calls: constants, types,
                                                                          subclassing, re-exports)
  cochange  P(B changes | A changes) = c    =>  A impacts B with weight c  (coupling no static analysis sees)
  import    file A imports symbol F by name =>  F impacts A's module level (non-call uses: subclassing, re-exports)
A file's rank is its best node (its module level, any of its symbols, or "part of the change"); see ImpactGraph.

Scoring: a seed starts at its seed weight (signature/deleted/renamed 1.0, body/module 0.8, moved 0.5). Each hop
multiplies by the edge weight and by `decay`. With max-combination a node's score is the best single path, found
exactly by `max_depth` rounds of relaxation (a bounded Bellman-Ford on max-product), and the path that produced it is
kept as the explanation. With noisy-OR, several independent paths reinforce each other: 1 - prod(1 - s_i).

Why max is the default: deterministic, explainable with exactly one path, and ten weak name-only guesses cannot add up
to look like one strong exact dependency. Noisy-OR rewards corroboration; Phase 7 measures both.
"""
import posixpath
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .callgraph import CallGraph, SymRef
from .changes import ChangeSet
from .cochange import CoChangeModel

CALL_WEIGHT = {"exact": 1.0, "probable": 0.7, "weak": 0.3}
SEED_WEIGHT = {"signature": 1.0, "deleted": 1.0, "renamed": 1.0, "body": 0.8, "moved": 0.5}
MODULE_SEED = 0.8
IMPORTS_ONLY_SEED = 0.3       # a file changing what IT imports rarely changes behaviour for files that import it


@dataclass(frozen=True)
class Params:
    decay: float = 0.6
    max_depth: int = 4
    combine: str = "max"                    # max | noisy_or
    import_weight: float = 0.5
    cochange_factor: float = 1.0            # multiplies co-change confidence
    use_calls: bool = True                  # switches for the Phase 7 ablations
    use_imports: bool = True
    use_cochange: bool = True
    use_weak: bool = True
    min_score: float = 0.01                 # stop propagating below this
    # v2 (tuned on the development pairs, judged on held-out pairs; off = the pre-registered v1 method)
    use_folder: bool = False                # a changed file weakly impacts code files in its own folder
    folder_weight: float = 0.4
    churn_tiebreak: bool = False            # among near-equal scores, files that change often rank first
    tiered: bool = False                    # v3: every file of the change ranks above every file beyond it


Node = tuple                                # ("sym", path, idx) | ("file", path)


def sym_node(ref: SymRef) -> Node:
    return ("sym", ref.path, ref.idx)


def file_node(path: str) -> Node:
    return ("file", path)


@dataclass(frozen=True)
class Step:
    node: Node
    edge: str                               # seed | call | import | cochange | folder
    reason: str                             # human-readable: "calls parse() which changed"


@dataclass
class Impact:
    node: Node
    score: float
    distance: int                           # hops from the nearest seed on the best path (0 = changed itself)
    path: list[Step] = field(default_factory=list)   # seed ... this node
    support: float = 0.0                    # the other combination's score (noisy-OR when ranking by max): breaks ties
                                            # in favour of nodes reached by several independent paths

    @property
    def kind(self) -> str:
        return self.node[0]

    @property
    def path_str(self) -> str:
        return self.node[1]

    @property
    def edge_types(self) -> list[str]:
        return [s.edge for s in self.path[1:]]

    @property
    def reason(self) -> str:
        return self.path[-1].reason if self.path else ""


@dataclass
class ImpactResult:
    seeds: list[Impact]
    symbols: list[Impact]                   # impacted symbols (not seeds), best first
    files: list[Impact]                     # impacted files incl. files of changed symbols, best first
    ms: int = 0
    params: Params = field(default_factory=Params)

    def ranked_files(self, exclude_changed: bool = False) -> list[str]:
        return [f.path_str for f in self.files if not (exclude_changed and f.distance == 0)]


class ImpactGraph:
    """Reverse adjacency: out[node] = [(impacted node, weight, edge type, reason)].

    Node meanings:
      ("sym", path, idx)   this function / method / class may behave differently
      ("file", path)       this file's MODULE-LEVEL code is affected (its constants, bindings, top-level statements):
                           only these spread through plain file imports, so one changed function does not light up
                           every file that happens to import its file
      ("changed", path)    this file is part of the change: the source of co-change edges
    """

    def __init__(self, calls: CallGraph, importers_of: dict[str, list[str]], cochange: CoChangeModel | None,
                 params: Params = Params()):
        self.p = params
        self.calls = calls
        self.out: dict[Node, list[tuple[Node, float, str, str]]] = defaultdict(list)
        if params.use_calls:
            for e in calls.edges:
                if e.confidence == "weak" and not params.use_weak:
                    continue
                target = sym_node(e.caller) if e.caller is not None else file_node(e.caller_path)
                self.out[sym_node(e.callee)].append((target, CALL_WEIGHT[e.confidence], "call",
                                                     f"calls {calls.name(e.callee)}() ({e.confidence}, line {e.line})"))
        if params.use_imports:
            for path, ref in calls.uses:                    # file imports this symbol by name
                if path != ref.path:
                    self.out[sym_node(ref)].append((file_node(path), params.import_weight, "import",
                                                    f"imports {calls.name(ref)} from {ref.path}"))
            for target, importers in importers_of.items():  # file imports a file whose module-level code changed
                for src in importers:
                    self.out[file_node(target)].append((file_node(src), params.import_weight, "import", f"imports {target}"))
        if params.use_cochange and cochange is not None:
            for src, rules in cochange.rules.items():
                for r in rules:
                    w = min(1.0, r.confidence * params.cochange_factor)
                    edge = (file_node(r.target), w, "cochange",
                            f"changed together with {src} in {round(r.confidence * 100)}% of its commits ({r.support} shared)")
                    self.out[("changed", src)].append(edge)
                    self.out[file_node(src)].append(edge)

        self.churn = cochange.file_commits if cochange is not None else {}
        if params.use_folder:
            by_dir: dict[str, list[str]] = defaultdict(list)
            for path in calls.symbols:
                by_dir[posixpath.dirname(path)].append(path)
            for path in calls.symbols:
                for other in by_dir[posixpath.dirname(path)]:
                    if other != path:
                        self.out[("changed", path)].append((file_node(other), params.folder_weight, "folder",
                                                            f"is in the same folder as {path}"))

    def label(self, node: Node) -> str:
        if node[0] == "sym":
            return f"{node[1]}::{self.calls.name(SymRef(node[1], node[2]))}"
        return node[1]


def seeds_from(changes: ChangeSet, calls: CallGraph) -> dict[Node, tuple[float, str]]:
    """Changed symbols (in the BASE tree, where their callers live) and files with changed module-level code."""
    seeds: dict[Node, tuple[float, str]] = {}

    def put(node, w, why):
        if w > seeds.get(node, (0.0, ""))[0]:
            seeds[node] = (w, why)

    for f in changes.files:
        for s in f.semantic_symbols:
            w = SEED_WEIGHT.get(s.change)
            if not w or s.old is None:
                continue                                    # added symbols: nothing in the base calls them yet
            ref = s.old
            syms = calls.symbols.get(ref.path)
            # the change set parsed the same base bytes, so indexes line up; verify by name and fall back by name
            if syms is None:
                continue
            if not (ref.idx < len(syms) and syms[ref.idx].name == s.name.rsplit(".", 1)[-1]):
                cand = [i for i, x in enumerate(syms) if (f"{x.parent}.{x.name}" if x.parent else x.name) == s.name]
                if not cand:
                    continue
                ref = SymRef(ref.path, cand[0])
            put(sym_node(ref), w, f"{s.change} change to {s.name}" + (f" ({s.note})" if s.note else ""))
        if f.module_changed and f.old_path:
            if f.imports_only:
                put(file_node(f.old_path), IMPORTS_ONLY_SEED, f"imports of {f.old_path} changed")
            else:
                put(file_node(f.old_path), MODULE_SEED, f"module-level code of {f.old_path} changed")
        if f.status in ("deleted", "renamed") and f.old_path and f.old_path in calls.symbols:
            put(file_node(f.old_path), 1.0 if f.status == "deleted" else SEED_WEIGHT["moved"],
                f"{f.old_path} was {'deleted' if f.status == 'deleted' else 'moved to ' + f.path}")
        if f.old_path and not f.cosmetic_only and f.category not in ("lockfile",):
            strength = max([SEED_WEIGHT.get(x.change, 0.0) for x in f.semantic_symbols]
                           + [MODULE_SEED if f.module_changed and not f.imports_only else 0.0,
                              IMPORTS_ONLY_SEED if f.imports_only else 0.0,
                              1.0 if f.status == "deleted" else 0.0,
                              MODULE_SEED if f.error or f.category not in ("code", "test") else 0.0,
                              0.5 if f.semantic_symbols else 0.0])   # added symbols only: still a change to the file
            if strength:
                put(("changed", f.old_path), strength, f"{f.old_path} is part of the change")
        if f.category in ("code", "test") and f.old_path and not f.cosmetic_only and not f.semantic_symbols \
                and not f.module_changed and f.error:
            # we could not analyse the file's symbols (diff did not apply, parse failed): treat the file as changed
            put(file_node(f.old_path), MODULE_SEED, f"{f.old_path} changed (symbols unknown: {f.error})")
    return seeds


def propagate(graph: ImpactGraph, seeds: dict[Node, tuple[float, str]]) -> ImpactResult:
    t0 = time.perf_counter()
    p = graph.p
    best: dict[Node, float] = {}
    depth: dict[Node, int] = {}
    prev: dict[Node, tuple[Node | None, str, str]] = {}
    for n, (w, why) in seeds.items():
        best[n], depth[n], prev[n] = w, 0, (None, "seed", why)

    frontier = set(seeds)
    # bounded Bellman-Ford: round k finds every best path of k hops (the hop limit is also enforced through `depth`)
    for _ in range(p.max_depth):
        nxt: set[Node] = set()
        for u in frontier:
            su = best[u]
            for v, w, kind, why in graph.out.get(u, ()):
                hop = 1
                sv = su * w * p.decay
                if sv < p.min_score:
                    continue
                dv = depth[u] + hop
                if dv > p.max_depth:
                    continue
                if sv > best.get(v, 0.0) + 1e-12:
                    best[v], depth[v], prev[v] = sv, dv, (u, kind, why)
                    nxt.add(v)
        if not nxt:
            break
        frontier = nxt
    agg = _noisy_or(graph, best, seeds)
    score_of, support_of = (agg, best) if p.combine == "noisy_or" else (best, agg)

    def path_of(n: Node) -> list[Step]:
        steps: list[Step] = []
        cur: Node | None = n
        seen = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            u, kind, why = prev[cur]
            steps.append(Step(cur, kind, why))
            cur = u
        return steps[::-1]

    def impact(n: Node) -> Impact:
        steps = path_of(n)
        hops = len(steps) - 1
        return Impact(n, round(score_of[n], 6), hops, steps, round(support_of[n], 6))

    seeds_out = [impact(n) for n in seeds]
    syms = sorted((impact(n) for n in best if n[0] == "sym" and n not in seeds), key=_rank)
    files = _rank_files(best, score_of, support_of, impact)
    if p.churn_tiebreak:
        churn = graph.churn
        key = lambda i: (-round(i.score, 3), -i.support, -churn.get(i.path_str, 0), i.distance, i.node)
        files.sort(key=key)
        syms.sort(key=key)
    if p.tiered:
        files.sort(key=lambda i: i.distance != 0)          # stable: keeps the score order inside each tier
    return ImpactResult(seeds_out, syms, files, int((time.perf_counter() - t0) * 1000), p)


def _rank_files(best, score_of, support_of, impact) -> list[Impact]:
    """A file's impact = its best node: its module-level node, any of its symbols, or its "changed" marker. The file
    inherits that node's score and explanation; distance 0 when the file is part of the change."""
    by_file: dict[str, Node] = {}
    for n in best:
        path = n[1]
        cur = by_file.get(path)
        if cur is None or (score_of[n], support_of[n]) > (score_of[cur], support_of[cur]):
            by_file[path] = n
    out = []
    for path, n in by_file.items():
        i = impact(n)
        out.append(Impact(("file", path), i.score, 0 if n[0] == "changed" or i.distance == 0 else i.distance,
                          i.path, i.support))
    return sorted(out, key=_rank)


def _rank(i: Impact):
    return (-i.score, -i.support, i.distance, i.node)


def _noisy_or(graph: ImpactGraph, best: dict[Node, float], seeds) -> dict[Node, float]:
    """One aggregation pass: a node's score = 1 - prod(1 - s(u) * w * decay) over every in-neighbour u that was reached
    (seeds keep their own weight). Cheap and cycle-safe; it lets independent evidence add up."""
    incoming: dict[Node, list[float]] = defaultdict(list)
    for u, su in best.items():
        for v, w, kind, _ in graph.out.get(u, ()):
            if v in best:
                incoming[v].append(su * w * graph.p.decay)
    out = dict(best)
    for v, contribs in incoming.items():
        if v in seeds:
            continue
        miss = 1.0
        for c in contribs:
            miss *= (1.0 - min(c, 1.0))
        out[v] = max(best[v], 1.0 - miss)
    return out


def apply_change_paths(result: ImpactResult, changes: ChangeSet) -> ImpactResult:
    """Express the file ranking in the CHANGED tree: the graph describes the base, so it knows files by their old paths
    and has never seen files the change adds.
      - renamed files are listed under their new path;
      - deleted files leave the ranking (they stay as seeds and in explanations: their callers are still impacted);
      - added code/test files join at distance 0 with the strength of their change (they are part of it).
    Without this a large refactor listed its deleted files on top and its new files nowhere (found in the evaluation).
    """
    renamed = {f.old_path: f.path for f in changes.files if f.old_path and f.old_path != f.path and f.status != "deleted"}
    deleted = {f.old_path for f in changes.files if f.status == "deleted" and f.old_path}
    out: list[Impact] = []
    seen: set[str] = set()
    for i in result.files:
        path = i.path_str
        if path in deleted:
            continue
        new = renamed.get(path, path)
        if new in seen:
            continue
        seen.add(new)
        out.append(Impact(("file", new), i.score, i.distance, i.path, i.support) if new != path else i)
    for f in changes.files:
        if f.status == "deleted" or f.path in seen or f.category not in ("code", "test") or f.cosmetic_only:
            continue
        strength = max([SEED_WEIGHT.get(x.change, 0.5 if x.change == "added" else 0.0) for x in f.semantic_symbols]
                       + [MODULE_SEED if f.module_changed else 0.0, 0.5])
        out.append(Impact(("file", f.path), strength, 0, [Step(("file", f.path), "seed", f"{f.path} is part of the change")],
                          strength))
        seen.add(f.path)
    keep_order = {id(i): n for n, i in enumerate(result.files)}
    if result.params.tiered:
        out.sort(key=lambda i: (i.distance != 0, -i.score, -i.support, keep_order.get(id(i), 10**9)))
    else:
        out.sort(key=lambda i: (-i.score, -i.support, keep_order.get(id(i), 10**9)))
    result.files = out
    return result


def blast_radius(changes: ChangeSet, calls: CallGraph, importers_of: dict[str, list[str]],
                 cochange: CoChangeModel | None, params: Params = Params()) -> ImpactResult:
    graph = ImpactGraph(calls, importers_of, cochange, params)
    return apply_change_paths(propagate(graph, seeds_from(changes, calls)), changes)
