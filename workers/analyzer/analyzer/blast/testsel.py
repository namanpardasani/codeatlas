"""Test impact analysis: which tests should run for a change, instead of the whole suite.

A test unit is a pytest/unittest test (a `test_*` function or method, possibly in a `Test*` class) or a JS/TS test case
(`it(...)` / `test(...)`, named with its `describe(...)` path). For each unit:

  score = max over the calls made inside the unit of  impact(callee) x call weight x decay
          (impact(callee) comes from Phase 3: a changed symbol has its seed weight, an impacted one its propagated score)
  plus a weaker file-level score when the unit's file imports a file whose module-level code changed.

Selected = units scoring >= threshold, ranked, plus every unit in a test file the change itself modified (always run
the tests that changed). The result says "N of M tests (X%)" and gives a command for the detected runner.

Safety: static analysis misses dynamic dispatch, fixtures, config and global setup. When the change touches what every
test depends on (test setup such as conftest.py or jest.setup, build/dependency files, runtime config), or when too much
of the changed code is unresolved, or when source changed but no test reaches it, the answer is "run the full suite",
with the reason, instead of a confident-looking subset.
"""
import json
import re
from dataclasses import dataclass, field

from ..inventory import is_test_path
from .callgraph import CallGraph, SymRef
from .changes import ChangeSet
from .impact import CALL_WEIGHT, ImpactResult
from .snapshot import Snapshot

THRESHOLD = 0.1                  # fixed before the test-selection evaluation
FILE_LEVEL_FACTOR = 0.5          # a test file that only imports impacted code: weaker than calling it
MAX_UNRESOLVED_SHARE = 0.4       # above this share of unresolved calls in the changed files, do not trust a subset


@dataclass
class TestUnit:
    file: str
    name: str                     # "TestFoo::test_bar" (pytest node id tail) or "suite > case" (JS)
    start_line: int
    end_line: int
    framework: str                # pytest | jest | vitest | mocha | node | unknown


@dataclass
class SelectedTest:
    unit: TestUnit
    score: float
    reason: str


@dataclass
class TestSelection:
    total: int
    selected: list[SelectedTest] = field(default_factory=list)
    new_tests: list[TestUnit] = field(default_factory=list)   # tests the change adds (not in the base: always run)
    full_suite: bool = False
    full_suite_reasons: list[str] = field(default_factory=list)
    command: str = ""
    framework: str = "unknown"

    @property
    def ratio(self) -> float:
        return len(self.selected) / self.total if self.total else 0.0

    @property
    def files(self) -> list[str]:
        return list(dict.fromkeys(s.unit.file for s in self.selected))

    def summary(self) -> str:
        if self.total == 0 and not self.new_tests:
            return "this repository has no tests"
        if self.full_suite:
            return f"run the full suite ({'; '.join(self.full_suite_reasons)})"
        extra = f" + {len(self.new_tests)} new" if self.new_tests else ""
        return f"{len(self.selected)} of {self.total} tests selected ({self.ratio:.0%}){extra}"


# ---- discovering tests ---------------------------------------------------------------------------------------------

def detect_framework(snap: Snapshot, path: str) -> str:
    if path.endswith(".py"):
        return "pytest"
    res = snap.parsed.get(path)
    specs = {im.specifier for im in res.imports} if res else set()
    if "vitest" in specs:
        return "vitest"
    if any(s.startswith("@jest") for s in specs):
        return "jest"
    pkg = snap.files.get("package.json")
    if pkg is not None:
        return _package_runner(snap)
    return "node" if "node:test" in specs else "unknown"


def _package_runner(snap: Snapshot) -> str:
    """Test runner named in package.json (devDependencies or scripts), cached on the snapshot."""
    if snap.runner is not None:
        return snap.runner
    runner = "unknown"
    text = snap.read_text("package.json") if snap.read_text else None
    if text:
        try:
            pkg = json.loads(text)
            deps = {**(pkg.get("devDependencies") or {}), **(pkg.get("dependencies") or {})}
            script = json.dumps(pkg.get("scripts") or {})
            for name in ("vitest", "jest", "mocha", "ava", "tap"):
                if name in deps or re.search(rf"\b{name}\b", script):
                    runner = name
                    break
        except (ValueError, AttributeError, TypeError):
            pass
    snap.runner = runner
    return runner


def discover_tests(snap: Snapshot, parsed: dict | None = None) -> list[TestUnit]:
    """Test units of a snapshot (or of `parsed`, e.g. the changed versions of some files)."""
    units: list[TestUnit] = []
    for path, res in (parsed if parsed is not None else snap.parsed).items():
        if not is_test_path(path):
            continue
        fw = detect_framework(snap, path)
        if path.endswith(".py"):
            by_name = {s.name: s for s in res.symbols if s.kind == "class"}
            for s in res.symbols:
                if not s.name.startswith("test"):
                    continue
                if s.kind == "function" and s.parent is None:
                    units.append(TestUnit(path, s.name, s.start_line, s.end_line, fw))
                elif s.kind == "method" and s.parent and s.parent in by_name and \
                        (s.parent.startswith("Test") or by_name[s.parent].bases):
                    units.append(TestUnit(path, f"{s.parent}::{s.name}", s.start_line, s.end_line, fw))
        else:
            suites = sorted((t for t in res.tests if t.kind == "suite"), key=lambda t: (t.start_line, -t.end_line))
            for t in res.tests:
                if t.kind != "test":
                    continue
                chain = [x.name for x in suites if x.start_line <= t.start_line and t.end_line <= x.end_line and x is not t]
                units.append(TestUnit(path, " > ".join(chain + [t.name]), t.start_line, t.end_line, fw))
    units.sort(key=lambda u: (u.file, u.start_line, u.name))
    return units


# ---- selecting -----------------------------------------------------------------------------------------------------

def select_tests(snap: Snapshot, calls: CallGraph, changes: ChangeSet, impact: ImpactResult,
                 threshold: float = THRESHOLD, decay: float | None = None) -> TestSelection:
    units = discover_tests(snap)
    sel = TestSelection(total=len(units))
    d = impact.params.decay if decay is None else decay
    sym_score: dict[SymRef, float] = {}
    for i in list(impact.seeds) + list(impact.symbols):
        if i.node[0] == "sym":
            ref = SymRef(i.node[1], i.node[2])
            sym_score[ref] = max(sym_score.get(ref, 0.0), i.score)
    file_score = {i.node[1]: i.score for i in impact.seeds if i.node[0] == "file"}
    for i in impact.files:
        if i.path and i.path[-1].node[0] == "file":
            file_score[i.path_str] = max(file_score.get(i.path_str, 0.0), i.score)

    # per test file: call sites by line with their callee's impact
    hits_by_file: dict[str, list[tuple[int, float, str]]] = {}
    for e in calls.edges:
        if not is_test_path(e.caller_path):
            continue
        s = sym_score.get(e.callee)
        if s:
            hits_by_file.setdefault(e.caller_path, []).append(
                (e.line, s * CALL_WEIGHT[e.confidence] * d, f"calls {calls.name(e.callee)}() which is impacted ({s:.2f})"))
    # file level: only module-level changes (constants, top-level statements) reach every test in an importing file;
    # a test that uses a changed FUNCTION shows up through its own call sites above
    imported_by_file: dict[str, tuple[float, str]] = {}
    for target, importers in snap.importers_of.items():
        s = file_score.get(target)
        if not s:
            continue
        for path in importers:
            if is_test_path(path) and s > imported_by_file.get(path, (0.0, ""))[0]:
                imported_by_file[path] = (s, f"imports {target} whose module code changed")

    # tests the change edits: base units overlapping deleted lines; changed-version units overlapping added lines
    edited_old: dict[str, set[int]] = {}
    edited_new: dict[str, set[int]] = {}
    for f in changes.files:
        if f.category == "test" and not f.cosmetic_only:
            if f.old_path:
                edited_old[f.old_path] = f.lines_old
            edited_new[f.path] = f.lines_new
    new_units = discover_tests(snap, {p: r for p, r in changes.new_parsed.items() if p in edited_new})
    base_keys = {(u.file, u.name) for u in units}
    touched_new = {(u.file, u.name) for u in new_units
                   if any(u.start_line <= ln <= u.end_line for ln in edited_new.get(u.file, ()))}
    sel.new_tests = [u for u in new_units if (u.file, u.name) in touched_new and (u.file, u.name) not in base_keys]
    for u in units:
        best, why = 0.0, ""
        for line, s, r in hits_by_file.get(u.file, ()):
            if u.start_line <= line <= u.end_line and s > best:
                best, why = s, r
        imp = imported_by_file.get(u.file)
        if imp and imp[0] * FILE_LEVEL_FACTOR * d > best:
            best, why = imp[0] * FILE_LEVEL_FACTOR * d, imp[1]
        if any(u.start_line <= ln <= u.end_line for ln in edited_old.get(u.file, ())) or (u.file, u.name) in touched_new:
            best, why = 1.0, "the change edits this test"
        if best >= threshold:
            sel.selected.append(SelectedTest(u, round(best, 4), why))
    sel.selected.sort(key=lambda x: (-x.score, x.unit.file, x.unit.start_line))

    _fallbacks(sel, snap, calls, changes)
    fws = [s.unit.framework for s in sel.selected] or [u.framework for u in units]
    sel.framework = max(set(fws), key=fws.count) if fws else "unknown"
    sel.command = command_for(sel)
    return sel


def _fallbacks(sel: TestSelection, snap: Snapshot, calls: CallGraph, changes: ChangeSet) -> None:
    if sel.total == 0 and not sel.new_tests:
        return                                   # no tests exist: "run the full suite" would be advice about nothing
    reasons: list[str] = []
    cats = {f.category for f in changes.files if not f.cosmetic_only}
    if "test_setup" in cats:
        reasons.append("test setup changed (" + ", ".join(f.path for f in changes.files if f.category == "test_setup")[:120] + ")")
    if "build" in cats:
        reasons.append("build or dependency files changed (" +
                       ", ".join(f.path for f in changes.files if f.category == "build")[:120] + ")")
    if "config" in cats:
        reasons.append("runtime configuration changed")
    changed_src = {f.old_path for f in changes.files if f.category == "code" and f.old_path and not f.cosmetic_only}
    if changed_src:
        total = sum(len(snap.parsed[p].calls) for p in changed_src if p in snap.parsed)
        unresolved = sum(1 for u in calls.unresolved if u.path in changed_src and u.reason in ("dynamic", "ambiguous"))
        if total >= 20 and unresolved / total > MAX_UNRESOLVED_SHARE:
            reasons.append(f"{unresolved} of {total} calls in the changed files are dynamic or ambiguous")
        if not sel.selected and not sel.new_tests and changes.changed_symbols:
            reasons.append("source changed but no test reaches it statically")
    if reasons:
        sel.full_suite = True
        sel.full_suite_reasons = reasons


def command_for(sel: TestSelection) -> str:
    if sel.full_suite or not (sel.selected or sel.new_tests):
        return {"pytest": "pytest", "vitest": "npx vitest run", "jest": "npx jest", "mocha": "npx mocha",
                "ava": "npx ava"}.get(sel.framework, "")
    files = list(dict.fromkeys(sel.files + [u.file for u in sel.new_tests]))
    fw = sel.framework
    if fw == "pytest":
        if len(sel.selected) <= 40:
            return "pytest " + " ".join(f"{s.unit.file}::{s.unit.name}" for s in sel.selected)
        return "pytest " + " ".join(files)
    names = [s.unit.name.split(" > ")[-1] for s in sel.selected]
    pattern = "|".join(re.escape(n) for n in dict.fromkeys(names))[:400]
    if fw == "vitest":
        return f"npx vitest run {' '.join(files)}" + (f" -t \"{pattern}\"" if len(names) <= 20 else "")
    if fw == "jest":
        return f"npx jest {' '.join(files)}" + (f" -t \"{pattern}\"" if len(names) <= 20 else "")
    if fw == "ava":
        return f"npx ava {' '.join(files)}" + "".join(f" --match \"{n}\"" for n in list(dict.fromkeys(names))[:10]) \
            if len(names) <= 10 else f"npx ava {' '.join(files)}"
    if fw == "mocha":
        return f"npx mocha {' '.join(files)}" + (f" --grep \"{pattern}\"" if len(names) <= 20 else "")
    return " ".join(files)
