import random

import pytest

from analyzer.graph import find_cycles
from analyzer.graph.reference import reference_cycles, reference_graph

from graph_cases import CASES, chain, random_graph, ring, todo


def graph_of(nodes, edges):
    """Cycle tests use the REFERENCE builder so they do not depend on your build_graph."""
    return reference_graph(nodes, edges)


@pytest.mark.parametrize("name", CASES)
def test_known_cases(name):
    nodes, pairs, expected = CASES[name]
    from graph_cases import E
    assert todo(find_cycles, graph_of(nodes, E(pairs))) == expected


def test_long_chain_has_no_cycles_and_does_not_recurse():
    nodes, edges = chain(5000)
    assert todo(find_cycles, graph_of(nodes, edges)) == []


def test_huge_ring_is_one_cycle_and_does_not_recurse():
    nodes, edges = ring(5000)
    result = todo(find_cycles, graph_of(nodes, edges))
    assert result == [sorted(nodes)]


def test_result_is_deterministic_under_shuffled_input():
    nodes, edges = random_graph(3)
    base = todo(find_cycles, graph_of(nodes, edges))
    rng = random.Random(5)
    for _ in range(5):
        n2, e2 = nodes[:], edges[:]
        rng.shuffle(n2), rng.shuffle(e2)
        assert find_cycles(graph_of(n2, e2)) == base


@pytest.mark.parametrize("seed", range(40))
def test_matches_networkx_on_random_graphs(seed):
    nodes, edges = random_graph(seed, n=40, density=0.05)
    g = graph_of(nodes, edges)
    assert todo(find_cycles, g) == reference_cycles(g)


def test_reference_itself_agrees_with_the_hand_checked_cases():
    """Guards the guard: if networkx and the expectations ever disagree, the fixture is wrong."""
    from graph_cases import E
    for name, (nodes, pairs, expected) in CASES.items():
        assert reference_cycles(graph_of(nodes, E(pairs))) == expected, name
