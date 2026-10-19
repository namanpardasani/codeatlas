"""networkx reference implementations, used ONLY to cross-check the hand-written ones in tests.
Never imported by the pipeline for the graph/cycle steps."""
import networkx as nx

from .types import DependencyGraph, Edge


def reference_graph(nodes: list[str], edges: list[Edge]) -> DependencyGraph:
    node_set = set(nodes)
    g = nx.DiGraph()
    g.add_nodes_from(node_set)
    for e in edges:
        if e.source not in node_set or e.target not in node_set:
            raise ValueError(f"edge references unknown node: {e}")
        if e.source != e.target:
            g.add_edge(e.source, e.target)
    ordered = sorted(g.nodes)
    return DependencyGraph(
        nodes=ordered,
        successors={n: sorted(g.successors(n)) for n in ordered},
        predecessors={n: sorted(g.predecessors(n)) for n in ordered},
    )


def _to_nx(graph: DependencyGraph) -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_nodes_from(graph.nodes)
    for n, outs in graph.successors.items():
        g.add_edges_from((n, m) for m in outs)
    return g


def reference_cycles(graph: DependencyGraph) -> list[list[str]]:
    sccs = [sorted(c) for c in nx.strongly_connected_components(_to_nx(graph)) if len(c) >= 2]
    return sorted(sccs, key=lambda c: c[0])


def reference_pagerank(graph: DependencyGraph, alpha: float = 0.85) -> dict[str, float]:
    # tight tolerance: networkx's default (1e-6) stops earlier than our implementation
    return nx.pagerank(_to_nx(graph), alpha=alpha, tol=1e-12, max_iter=1000)


def reference_betweenness(graph: DependencyGraph) -> dict[str, float]:
    return nx.betweenness_centrality(_to_nx(graph))
