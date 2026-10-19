from .types import DependencyGraph


def find_cycles(graph: DependencyGraph) -> list[list[str]]:
    """Tarjan's strongly-connected-components algorithm, written without recursion.

    A group of files that can all reach each other (A -> B -> C -> A) is one SCC.
    Any SCC with 2+ files is a circular dependency. O(N + E). Groups are sorted inside and
    by first file across, so the output is deterministic.
    """
    index: dict[str, int] = {}   # order in which each file was first visited
    low: dict[str, int] = {}     # lowest index reachable from this file
    on_stack: set[str] = set()
    stack: list[str] = []        # files visited but not yet assigned to a group
    cycles: list[list[str]] = []
    counter = 0

    for root in graph.nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, 0)]  # (file, position of the next neighbour to look at)

        while work:
            node, i = work.pop()
            neighbours = graph.successors[node]

            if i < len(neighbours):
                work.append((node, i + 1))          # come back for the next neighbour later
                nxt = neighbours[i]
                if nxt not in index:                # unvisited: go deeper
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, 0))
                elif nxt in on_stack:               # points back into the current path: cycle
                    low[node] = min(low[node], index[nxt])
            else:
                # finished all neighbours of `node`
                if low[node] == index[node]:        # `node` is the root of a group
                    group = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        group.append(member)
                        if member == node:
                            break
                    if len(group) >= 2:
                        cycles.append(sorted(group))
                if work:                            # tell the parent what we learned
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])

    return sorted(cycles, key=lambda g: g[0])
