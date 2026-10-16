"""Shared fixtures for the graph tests."""
import random

import pytest

from analyzer.graph.types import Edge


def E(pairs):
    return [Edge(a, b) for a, b in pairs]


# name -> (nodes, edge pairs, expected cycle groups)
CASES = {
    "empty": ([], [], []),
    "single_node": (["a"], [], []),
    "chain": (list("abc"), [("a", "b"), ("b", "c")], []),
    "diamond_dag": (list("abcd"), [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")], []),
    "two_cycle": (list("ab"), [("a", "b"), ("b", "a")], [["a", "b"]]),
    "three_cycle_with_tail_and_head": (
        list("xabcy"), [("x", "a"), ("a", "b"), ("b", "c"), ("c", "a"), ("c", "y")], [["a", "b", "c"]]),
    "two_disjoint_cycles": (
        list("abcdef"), [("a", "b"), ("b", "a"), ("c", "d"), ("d", "c"), ("e", "f")],
        [["a", "b"], ["c", "d"]]),
    "overlapping_cycles_are_one_group": (
        list("abcd"), [("a", "b"), ("b", "c"), ("c", "a"), ("b", "d"), ("d", "b")], [["a", "b", "c", "d"]]),
    "self_loop_is_not_a_cycle": (list("ab"), [("a", "a"), ("a", "b")], []),
    "duplicate_edges": (list("ab"), [("a", "b"), ("a", "b"), ("b", "a")], [["a", "b"]]),
    "paths_like_files": (
        ["src/a.ts", "src/b.ts", "src/lib/c.ts"],
        [("src/a.ts", "src/b.ts"), ("src/b.ts", "src/lib/c.ts"), ("src/lib/c.ts", "src/a.ts")],
        [["src/a.ts", "src/b.ts", "src/lib/c.ts"]]),
}


def chain(n: int):
    nodes = [f"f{i:05d}" for i in range(n)]
    return nodes, [Edge(nodes[i], nodes[i + 1]) for i in range(n - 1)]


def ring(n: int):
    nodes, edges = chain(n)
    return nodes, edges + [Edge(nodes[-1], nodes[0])]


def random_graph(seed: int, n: int = 40, density: float = 0.06):
    rng = random.Random(seed)
    nodes = [f"n{i}" for i in range(n)]
    edges = [Edge(a, b) for a in nodes for b in nodes if rng.random() < density]  # may include self-loops
    edges += rng.sample(edges, k=min(5, len(edges)))  # plus some duplicates
    return nodes, edges


def todo(fn, *args, **kwargs):
    """Run a user-written function; SKIP (not fail) while it is still a TODO stub."""
    try:
        return fn(*args, **kwargs)
    except NotImplementedError:
        pytest.skip(f"TODO(user): {fn.__name__} not implemented yet")
