"""Graph metrics: fan-in/out, PageRank centrality, folder modules, cross-module edges."""
from collections import Counter
from dataclasses import dataclass, field

from .builder import build_graph
from .cycles import find_cycles
from .types import DependencyGraph, Edge

ROOT_MODULE = "(root)"


def fan_in_out(graph: DependencyGraph) -> dict[str, tuple[int, int]]:
    """node -> (fan_in, fan_out). fan_in = how many files import it; fan_out = how many it imports."""
    return {n: (len(graph.predecessors[n]), len(graph.successors[n])) for n in graph.nodes}


def pagerank(graph: DependencyGraph, damping: float = 0.85, max_iter: int = 100,
             tol: float = 1e-10) -> dict[str, float]:
    """PageRank by power iteration. Rank flows along import edges (A -> B gives B rank), so a
    file scores high when MANY files, themselves important, import it: shared cores like types,
    utils, base classes. Files that import nothing ("dangling" leaves) spread their rank evenly
    over all files, the standard fix that keeps the total at 1.0. O(iterations * (N + E))."""
    nodes = graph.nodes
    n = len(nodes)
    if n == 0:
        return {}
    rank = {v: 1.0 / n for v in nodes}
    for _ in range(max_iter):
        dangling = sum(rank[v] for v in nodes if not graph.successors[v])
        base = (1.0 - damping) / n + damping * dangling / n
        new = dict.fromkeys(nodes, base)
        for v in nodes:
            outs = graph.successors[v]
            if outs:
                share = damping * rank[v] / len(outs)
                for w in outs:
                    new[w] += share
        err = sum(abs(new[v] - rank[v]) for v in nodes)
        rank = new
        if err < n * tol:
            break
    return rank


def module_of(path: str, depth: int) -> str:
    folders = path.split("/")[:-1][:depth]
    return "/".join(folders) or ROOT_MODULE


def choose_depth(paths: list[str], max_depth: int = 3) -> int:
    """Folder depth that gives useful clusters. If one folder holds >=80% of the files (typically
    `src/`) and it splits into several sub-folders, look one level deeper."""
    depth = 1
    while depth < max_depth and paths:
        counts = Counter(module_of(p, depth) for p in paths)
        top, size = counts.most_common(1)[0]
        if top == ROOT_MODULE or size < 0.8 * len(paths):
            break
        deeper = {module_of(p, depth + 1) for p in paths if module_of(p, depth) == top}
        if len(deeper) < 2:
            break
        depth += 1
    return depth


def assign_modules(paths: list[str], depth: int | None = None) -> dict[str, str]:
    d = choose_depth(paths) if depth is None else depth
    return {p: module_of(p, d) for p in paths}


def module_edges(graph: DependencyGraph, modules: dict[str, str]):
    """Return (cross, internal): cross[(from_mod, to_mod)] = number of file edges between two
    different modules; internal[mod] = file edges that stay inside the module."""
    cross: Counter = Counter()
    internal: Counter = Counter()
    for a in graph.nodes:
        for b in graph.successors[a]:
            ma, mb = modules[a], modules[b]
            if ma == mb:
                internal[ma] += 1
            else:
                cross[(ma, mb)] += 1
    return dict(sorted(cross.items())), dict(sorted(internal.items()))


@dataclass
class GraphAnalysis:
    graph: DependencyGraph
    cycles: list[list[str]]
    fan: dict[str, tuple[int, int]]
    pagerank: dict[str, float]
    modules: dict[str, str]
    cross_module_edges: dict[tuple[str, str], int]
    internal_module_edges: dict[str, int]
    cycle_of: dict[str, int] = field(default_factory=dict)  # file -> index in `cycles`


def analyze(nodes: list[str], edges: list[Edge]) -> GraphAnalysis:
    graph = build_graph(nodes, edges)
    cycles = find_cycles(graph)
    modules = assign_modules(graph.nodes)
    cross, internal = module_edges(graph, modules)
    return GraphAnalysis(
        graph=graph, cycles=cycles, fan=fan_in_out(graph), pagerank=pagerank(graph),
        modules=modules, cross_module_edges=cross, internal_module_edges=internal,
        cycle_of={f: i for i, group in enumerate(cycles) for f in group},
    )
