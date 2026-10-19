import pytest

from analyzer.graph import build_graph
from analyzer.graph.metrics import (
    analyze, assign_modules, choose_depth, fan_in_out, module_edges, pagerank,
)
from analyzer.graph.reference import reference_graph, reference_pagerank
from analyzer.graph.types import Edge

from graph_cases import E, random_graph


def g(nodes, pairs):
    return build_graph(nodes, E(pairs))


def test_fan_in_and_out():
    graph = g(list("abcd"), [("a", "b"), ("a", "c"), ("b", "c"), ("d", "c")])
    fan = fan_in_out(graph)
    assert fan["c"] == (3, 0) and fan["a"] == (0, 2) and fan["b"] == (1, 1)


def test_pagerank_sums_to_one_and_ranks_the_shared_core_highest():
    # util is imported by everyone; a is imported by nobody
    graph = g(["a", "b", "c", "util"], [("a", "b"), ("a", "util"), ("b", "util"), ("c", "util")])
    pr = pagerank(graph)
    assert sum(pr.values()) == pytest.approx(1.0)
    assert max(pr, key=pr.get) == "util"
    assert pr["a"] < pr["b"] < pr["util"]


def test_pagerank_empty_and_single():
    assert pagerank(g([], [])) == {}
    assert pagerank(g(["a"], [])) == {"a": pytest.approx(1.0)}


@pytest.mark.parametrize("seed", range(10))
def test_pagerank_matches_networkx(seed):
    pytest.importorskip("scipy")  # networkx's pagerank needs scipy
    nodes, edges = random_graph(seed, n=30, density=0.08)
    graph = reference_graph(nodes, edges)
    mine, ref = pagerank(graph, tol=1e-12), reference_pagerank(graph)
    for n in graph.nodes:
        assert mine[n] == pytest.approx(ref[n], abs=1e-6)


def test_module_depth_picks_inside_src():
    paths = [f"src/{m}/f{i}.ts" for m in ("api", "ui", "db") for i in range(3)] + ["README.md"]
    assert choose_depth(paths) == 2
    mods = assign_modules(paths)
    assert mods["src/api/f0.ts"] == "src/api" and mods["README.md"] == "(root)"


def test_module_depth_stays_at_one_for_flat_top_level_folders():
    paths = ["api/a.py", "api/b.py", "web/c.py", "web/d.py"]
    assert choose_depth(paths) == 1 and assign_modules(paths)["api/a.py"] == "api"


def test_cross_and_internal_module_edges():
    graph = g(["api/a.py", "api/b.py", "web/c.py"],
              [("api/a.py", "api/b.py"), ("web/c.py", "api/a.py"), ("web/c.py", "api/b.py")])
    cross, internal = module_edges(graph, assign_modules(graph.nodes))
    assert cross == {("web", "api"): 2} and internal == {"api": 1}


def test_analyze_end_to_end():
    nodes = ["src/a.ts", "src/b.ts", "src/c.ts", "lib/u.ts"]
    edges = [Edge("src/a.ts", "src/b.ts"), Edge("src/b.ts", "src/a.ts"), Edge("src/c.ts", "lib/u.ts"),
             Edge("src/a.ts", "lib/u.ts"), Edge("src/a.ts", "src/a.ts")]
    a = analyze(nodes, edges)
    assert a.cycles == [["src/a.ts", "src/b.ts"]]
    assert a.cycle_of == {"src/a.ts": 0, "src/b.ts": 0}
    assert a.fan["lib/u.ts"] == (2, 0)
    assert a.cross_module_edges == {("src", "lib"): 2}
    assert max(a.pagerank, key=a.pagerank.get) == "lib/u.ts"
