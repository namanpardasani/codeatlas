from .types import DependencyGraph, Edge


def build_graph(nodes: list[str], edges: list[Edge]) -> DependencyGraph:
    """TODO(user): build the dependency graph from files and resolved edges.

    Contract (the tests in tests/test_graph_builder.py check each line):
      1. `nodes` may contain duplicates and be unsorted. Output nodes: sorted, unique.
         Isolated files (no edges) must still be nodes.
      2. `edges` may contain duplicates (same source/target, possibly different `kind`).
         Collapse them: one edge per (source, target). `kind` is not kept in the graph.
      3. Self-edges (source == target) are DROPPED.
      4. An edge whose source or target is not in `nodes` -> raise ValueError.
      5. Every node has an entry in `successors` and in `predecessors`, even if empty.
         Neighbour lists are sorted and unique.
      6. Deterministic: the same inputs in any order give the same graph.
      7. O(N + E): no scanning all edges per node.

    Hints: sets while collecting, sort once at the end. Think about why you need BOTH maps
    (fan-out is len(successors[n]); fan-in is len(predecessors[n]); "what depends on X?" is predecessors).
    """
    raise NotImplementedError("TODO(user): implement build_graph")
