"""Phase 3 of Blast Radius: impact propagation over calls, imports and co-change, with decay, depth limit,
max vs noisy-OR combination, explanation paths, ablation switches, and the end-to-end engine on a real git repo."""
from pathlib import Path

import pytest

from analyzer.blast.callgraph import CallEdge, CallGraph, SymRef
from analyzer.blast.changes import ChangeSet, FileChange, SymbolChange
from analyzer.blast.cochange import CoChangeModel, Rule
from analyzer.blast.engine import analyze_commit
from analyzer.blast.impact import ImpactGraph, Params, blast_radius, propagate, seeds_from
from analyzer.blast.snapshot import InProcessParser
from analyzer.parsing.types import Symbol
from gitutil import DAY, T0, commit, init


def S(path, name, i, start=1):
    return Symbol(name, "function", start, start + 1)


def graph_of(files: dict[str, list[str]], edges: list[tuple[str, str, str]], uses=()):
    """files: path -> symbol names. edges: (caller "path:name", callee "path:name", confidence)."""
    symbols = {p: [Symbol(n, "function", 1 + 3 * i, 2 + 3 * i) for i, n in enumerate(names)] for p, names in files.items()}

    def ref(s):
        p, n = s.split(":")
        return SymRef(p, files[p].index(n))
    g = CallGraph(symbols=symbols)
    for a, b, conf in edges:
        caller = None if a.endswith(":<module>") else ref(a)
        g.edges.append(CallEdge(a.split(":")[0], caller, ref(b), conf, 1, "call", "test"))
    g.uses = [(p, ref(s)) for p, s in uses]
    return g, ref


def change(path, name, idx, kind="body"):
    f = FileChange(path, path, "modified", "code")
    f.symbols.append(SymbolChange(kind, "function", name, SymRef(path, idx), SymRef(path, idx)))
    return f


def cs(*files):
    c = ChangeSet()
    c.files.extend(files)
    return c


CHAIN = {"a.py": ["e"], "b.py": ["d"], "c.py": ["c"], "d.py": ["b"], "e.py": ["a"], "f.py": ["z"]}
CHAIN_EDGES = [("b.py:d", "a.py:e", "exact"), ("c.py:c", "b.py:d", "exact"), ("d.py:b", "c.py:c", "exact"),
               ("e.py:a", "d.py:b", "exact"), ("f.py:z", "e.py:a", "exact")]


def test_decay_per_hop_and_depth_limit():
    g, ref = graph_of(CHAIN, CHAIN_EDGES)
    r = blast_radius(cs(change("a.py", "e", 0)), g, {}, None, Params(decay=0.6, max_depth=4))
    got = {s.node[1]: (round(s.score, 4), s.distance) for s in r.symbols}
    # seed body change 0.8; each exact call hop x 1.0 x 0.6; the 5th hop (f.py) is beyond max_depth
    assert got == {"b.py": (0.48, 1), "c.py": (0.288, 2), "d.py": (0.1728, 3), "e.py": (0.1037, 4)}


def test_confidence_weights_and_max_keeps_the_best_path():
    files = {"lib.py": ["target"], "x.py": ["strong"], "y.py": ["weakly"], "z.py": ["both"]}
    g, _ = graph_of(files, [("x.py:strong", "lib.py:target", "exact"), ("y.py:weakly", "lib.py:target", "weak"),
                            ("z.py:both", "x.py:strong", "exact"), ("z.py:both", "y.py:weakly", "probable")])
    r = blast_radius(cs(change("lib.py", "target", 0, "signature")), g, {}, None, Params())
    sc = {s.node[1]: s for s in r.symbols}
    assert sc["x.py"].score == pytest.approx(0.6) and sc["y.py"].score == pytest.approx(0.18)
    assert sc["z.py"].score == pytest.approx(0.36)                      # via x (0.6*0.6), not via y (0.18*0.7*0.6)
    assert [st.node[1] for st in sc["z.py"].path] == ["lib.py", "x.py", "z.py"]
    assert sc["z.py"].path[-1].reason.startswith("calls strong()")


def test_noisy_or_rewards_independent_paths():
    files = {"lib.py": ["t"], "p.py": ["p1"], "q.py": ["q1"], "r.py": ["both"]}
    g, _ = graph_of(files, [("p.py:p1", "lib.py:t", "exact"), ("q.py:q1", "lib.py:t", "exact"),
                            ("r.py:both", "p.py:p1", "exact"), ("r.py:both", "q.py:q1", "exact")])
    mx = blast_radius(cs(change("lib.py", "t", 0, "signature")), g, {}, None, Params(combine="max"))
    no = blast_radius(cs(change("lib.py", "t", 0, "signature")), g, {}, None, Params(combine="noisy_or"))
    both_max = next(s for s in mx.symbols if s.node[1] == "r.py")
    both_no = next(s for s in no.symbols if s.node[1] == "r.py")
    assert both_max.score == pytest.approx(0.36)
    assert both_no.score == pytest.approx(1 - (1 - 0.36) ** 2)         # two independent 0.36 paths
    assert both_max.support == pytest.approx(both_no.score)            # max mode keeps noisy-OR as the tie-breaker


def test_cycles_terminate():
    files = {"a.py": ["f"], "b.py": ["g"]}
    g, _ = graph_of(files, [("a.py:f", "b.py:g", "exact"), ("b.py:g", "a.py:f", "exact")])
    r = blast_radius(cs(change("a.py", "f", 0)), g, {}, None, Params(max_depth=50))
    assert [s.node[1] for s in r.symbols] == ["b.py"]


def test_body_change_does_not_flood_every_importer_of_the_file():
    files = {"lib.py": ["used", "other"], "user.py": ["u"], "bystander.py": ["b"]}
    g, _ = graph_of(files, [("user.py:u", "lib.py:used", "exact")])
    importers = {"lib.py": ["user.py", "bystander.py"]}
    r = blast_radius(cs(change("lib.py", "used", 0)), g, importers, None, Params())
    ranked = r.ranked_files()
    assert ranked[:2] == ["lib.py", "user.py"] and "bystander.py" not in ranked


def test_module_level_change_reaches_importers_and_imports_only_barely():
    files = {"lib.py": ["f"], "user.py": ["u"]}
    g, _ = graph_of(files, [])
    importers = {"lib.py": ["user.py"]}
    f = FileChange("lib.py", "lib.py", "modified", "code", module_changed=True)
    r = blast_radius(cs(f), g, importers, None, Params())
    assert next(x for x in r.files if x.path_str == "user.py").score == pytest.approx(0.8 * 0.5 * 0.6)
    f2 = FileChange("lib.py", "lib.py", "modified", "code", module_changed=True, imports_only=True)
    r2 = blast_radius(cs(f2), g, importers, None, Params())
    assert next(x for x in r2.files if x.path_str == "user.py").score == pytest.approx(0.3 * 0.5 * 0.6)


def test_symbol_imported_by_name_reaches_the_importer_without_a_call():
    files = {"base.py": ["Base"], "sub.py": ["Child"]}
    g, _ = graph_of(files, [], uses=[("sub.py", "base.py:Base")])     # class Child(Base): no call edge
    r = blast_radius(cs(change("base.py", "Base", 0, "signature")), g, {}, None, Params())
    hit = next(x for x in r.files if x.path_str == "sub.py")
    assert hit.score == pytest.approx(1.0 * 0.5 * 0.6) and hit.path[-1].edge == "import"


def test_cochange_edges_start_from_changed_files():
    files = {"router.py": ["route"], "views.py": ["v"]}
    g, _ = graph_of(files, [])
    cc = CoChangeModel(rules={"router.py": [Rule("router.py", "views.py", 9, 0.73)]})
    r = blast_radius(cs(change("router.py", "route", 0)), g, {}, cc, Params())
    v = next(x for x in r.files if x.path_str == "views.py")
    assert v.score == pytest.approx(0.8 * 0.73 * 0.6)
    assert "73% of its commits (9 shared)" in v.reason


def test_ablation_switches():
    files = {"a.py": ["f"], "b.py": ["g"], "c.py": ["h"]}
    g, _ = graph_of(files, [("b.py:g", "a.py:f", "weak")])
    cc = CoChangeModel(rules={"a.py": [Rule("a.py", "c.py", 3, 0.5)]})
    seeds = cs(change("a.py", "f", 0))
    assert set(blast_radius(seeds, g, {}, cc, Params()).ranked_files()) == {"a.py", "b.py", "c.py"}
    assert set(blast_radius(seeds, g, {}, cc, Params(use_weak=False)).ranked_files()) == {"a.py", "c.py"}
    assert set(blast_radius(seeds, g, {}, cc, Params(use_cochange=False)).ranked_files()) == {"a.py", "b.py"}
    assert set(blast_radius(seeds, g, {}, cc, Params(use_calls=False, use_cochange=False)).ranked_files()) == {"a.py"}


def test_added_symbols_are_not_seeds_but_deleted_files_are():
    g, _ = graph_of({"a.py": ["f"], "u.py": ["x"]}, [("u.py:x", "a.py:f", "exact")])
    added = FileChange("a.py", "a.py", "modified", "code")
    added.symbols.append(SymbolChange("added", "function", "g", None, SymRef("a.py", 5)))
    assert not [n for n in seeds_from(cs(added), g) if n[0] == "sym"]
    gone = FileChange("a.py", "a.py", "deleted", "code")
    gone.symbols.append(SymbolChange("deleted", "function", "f", SymRef("a.py", 0), None))
    r = blast_radius(cs(gone), g, {}, None, Params())
    assert next(s for s in r.symbols if s.node[1] == "u.py").score == pytest.approx(0.6)


def test_end_to_end_on_a_git_repo(tmp_path):
    r = tmp_path / "r"
    init(r)
    lib = "def parse(t):\n    return t.split(',')\n\n\ndef unused():\n    return 0\n"
    api = "from lib import parse\n\n\ndef load(t):\n    return parse(t)\n"
    cli = "from api import load\n\n\ndef main():\n    return load('a,b')\n"
    commit(r, T0, "ann", {"lib.py": lib, "api.py": api, "cli.py": cli, "other.py": "def z():\n    return 1\n"})
    for i in range(3):                             # lib.py and docs change together historically
        commit(r, T0 + (i + 1) * DAY, "ann", {"lib.py": lib + f"# v{i}\n", "notes.md": f"v{i}\n"})
    commit(r, T0 + 9 * DAY, "bob", {"lib.py": lib.replace("t.split(',')", "t.split(';')") + "# v2\n"})
    rep = analyze_commit(r, "HEAD", parser=InProcessParser())
    files = rep.impact.ranked_files()
    assert files[0] == "lib.py"
    assert files.index("api.py") < files.index("cli.py")              # 1 hop before 2 hops
    assert "notes.md" in files and "other.py" not in files            # co-change found it; nothing links other.py
    api_hit = next(f for f in rep.impact.files if f.path_str == "api.py")
    assert [s.edge for s in api_hit.path] == ["seed", "call"] and "parse()" in api_hit.reason
