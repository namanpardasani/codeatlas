from .types import DependencyGraph


def find_cycles(graph: DependencyGraph) -> list[list[str]]:
    """TODO(user): find circular dependencies = strongly connected components (SCCs) of size >= 2.

    Contract (tests/test_cycles.py checks each line):
      1. Return one list per SCC that has 2 or more files (a cycle group). Files that are
         not part of any cycle are not returned.
      2. Inside each group: files sorted. Across groups: sorted by their first file.
         (so the result is deterministic and easy to compare)
      3. Overlapping cycles (a->b->c->a and b->d->b) are ONE group {a,b,c,d}: an SCC is the
         maximal set of files that can all reach each other.
      4. Must be ITERATIVE: a 5,000-file chain or ring must not hit Python's recursion limit.
      5. O(N + E): Tarjan's or Kosaraju's algorithm. (Don't enumerate every simple cycle: the
         number of simple cycles can be exponential.)

    Hints: Tarjan needs an index, a lowlink, an "on stack" flag and an explicit work stack of
    (node, next-neighbour-position). Kosaraju needs a finish order + the transpose graph
    (you already have `predecessors`).
    """
    raise NotImplementedError("TODO(user): implement find_cycles")
