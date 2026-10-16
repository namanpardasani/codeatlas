import random

import pytest

from analyzer.graph import build_graph
from analyzer.graph.reference import reference_graph
from analyzer.graph.types import Edge

from graph_cases import CASES, E, random_graph, todo


def test_nodes_sorted_unique_and_isolated_files_kept():
    g = todo(build_graph, ["b", "a", "b", "z"], E([("a", "b")]))
    assert g.nodes == ["a", "b", "z"]
    assert g.successors["z"] == [] and g.predecessors["z"] == []


def test_duplicate_edges_collapse_regardless_of_kind():
    g = todo(build_graph, ["a", "b"], [Edge("a", "b", "import"), Edge("a", "b", "require"), Edge("a", "b")])
    assert g.successors["a"] == ["b"] and g.predecessors["b"] == ["a"]


def test_self_edges_are_dropped():
    g = todo(build_graph, ["a", "b"], E([("a", "a"), ("a", "b")]))
    assert g.successors["a"] == ["b"] and g.predecessors["a"] == []


def test_unknown_endpoint_raises_value_error():
    todo(build_graph, ["a"], [])  # skip while TODO
    with pytest.raises(ValueError):
        build_graph(["a"], E([("a", "ghost")]))
    with pytest.raises(ValueError):
        build_graph(["a"], E([("ghost", "a")]))


def test_successors_and_predecessors_are_consistent_and_sorted():
    nodes, edge_pairs, _ = CASES["overlapping_cycles_are_one_group"]
    g = todo(build_graph, nodes, E(edge_pairs))
    for n in g.nodes:
        assert g.successors[n] == sorted(set(g.successors[n]))
        assert g.predecessors[n] == sorted(set(g.predecessors[n]))
        for m in g.successors[n]:
            assert n in g.predecessors[m]
        for m in g.predecessors[n]:
            assert n in g.successors[m]


def test_input_order_does_not_matter():
    nodes, edges = random_graph(7)
    a = todo(build_graph, nodes, edges)
    rng = random.Random(1)
    n2, e2 = nodes[:], edges[:]
    rng.shuffle(n2), rng.shuffle(e2)
    assert build_graph(n2, e2) == a


@pytest.mark.parametrize("seed", range(25))
def test_matches_networkx_reference_on_random_graphs(seed):
    nodes, edges = random_graph(seed)
    mine = todo(build_graph, nodes, edges)
    assert mine == reference_graph(nodes, edges)
