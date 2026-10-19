from .types import DependencyGraph, Edge


def build_graph(nodes: list[str], edges: list[Edge]) -> DependencyGraph:
    """Build the dependency graph from files (nodes) and resolved imports (edges).

    Contract: nodes sorted + unique (isolated files kept); duplicate edges collapse (kind is
    not kept); self-edges dropped; an edge to/from an unknown file raises ValueError; every
    node has a sorted successors AND predecessors entry; deterministic; O(N + E).
    """
    node_list = sorted(set(nodes))  # sorted + unique
    known = set(node_list)

    # sets collapse duplicate edges automatically; every node gets an entry (even if empty)
    successors = {n: set() for n in node_list}
    predecessors = {n: set() for n in node_list}

    for edge in edges:
        if edge.source not in known or edge.target not in known:
            raise ValueError(f"edge points at an unknown file: {edge.source} -> {edge.target}")
        if edge.source == edge.target:
            continue  # a file importing itself is not a useful dependency
        successors[edge.source].add(edge.target)
        predecessors[edge.target].add(edge.source)

    return DependencyGraph(
        nodes=node_list,
        successors={n: sorted(v) for n, v in successors.items()},
        predecessors={n: sorted(v) for n, v in predecessors.items()},
    )
