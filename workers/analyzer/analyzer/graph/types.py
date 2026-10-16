from dataclasses import dataclass


@dataclass(frozen=True)
class Edge:
    """`source` imports `target` (both repo-relative file paths). Comes from resolved imports."""
    source: str
    target: str
    kind: str = "import"  # import | require | dynamic | reexport | from


@dataclass
class DependencyGraph:
    """Directed file-level graph. An edge A -> B means "A depends on (imports) B".

    Invariants (build_graph must establish them):
      * nodes: sorted, unique
      * successors[n] = sorted unique files that n imports;   every node has an entry (maybe [])
      * predecessors[n] = sorted unique files that import n;  every node has an entry (maybe [])
      * no self-edges
    """
    nodes: list[str]
    successors: dict[str, list[str]]
    predecessors: dict[str, list[str]]
