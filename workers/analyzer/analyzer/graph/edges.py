from collections.abc import Iterable

from ..resolve.types import ImportResolution
from .types import Edge


def edges_from_resolutions(resolutions: Iterable[ImportResolution], node_set: set[str]) -> list[Edge]:
    """Internal imports -> graph edges. Edges touching non-code files (css, json, images...) are
    dropped: the graph's nodes are source files. External and unresolved imports never become edges."""
    edges: list[Edge] = []
    for r in resolutions:
        if r.resolution.status != "internal" or r.from_path not in node_set:
            continue
        for target in r.resolution.targets:
            if target in node_set:
                edges.append(Edge(r.from_path, target, r.kind))
    return edges
