"""Incremental re-analysis must produce EXACTLY what a fresh full analysis of the same tree produces, while really
reusing the unchanged files. Two repos in the database: A is updated incrementally after each change, B is
re-analysed in full from scratch; every derived table is compared."""
import hashlib
import random

import pytest

from analyzer import analysis as analysis_mod
from analyzer import db
from analyzer.analysis import PIPELINE_VERSION, analyze_checkout
from analyzer.embeddings import HashEmbedder

try:
    conn = db.connect()
except Exception:  # noqa: BLE001
    conn = None
pytestmark = pytest.mark.skipif(conn is None, reason="Postgres not available")
EMB = HashEmbedder()


def block(name: str, extra: str = "") -> str:
    """A function with branches, >50 tokens and >6 lines, so it takes part in complexity and duplicate detection."""
    return f"""export function {name}(items: number[], limit: number, strict: boolean): number[] {{
  const out: number[] = [];
  for (let i = 0; i < items.length; i++) {{
    const item = items[i];
    if (item > limit && strict) {{
      out.push(item * 2 + {len(name)});
    }} else if (item < 0 || item === limit) {{
      out.push(-item);
    }}
  }}
  {extra}
  return out.sort((a, b) => b - a);
}}
"""


BASE = {
    "src/app.ts": 'import {clamp} from "./util";\nimport {nope} from "./helpers";\nimport {fmt} from "./lib/format";\nimport React from "react";\n'
                  'export function main() { return fmt(clamp(1, 0, 5)) }\n' + block("rankApp"),
    "src/util.ts": "export function clamp(v: number, lo: number, hi: number) {\n  if (v < lo) return lo;\n  if (v > hi) return hi;\n  return v;\n}\n",
    "src/lib/format.ts": 'import {clamp} from "../util";\nexport function fmt(n: number) { return String(clamp(n, 0, 99)) }\n',
    "src/lib/index.ts": 'export * from "./format";\n',
    "src/util.test.ts": 'import {clamp} from "./util";\ntest("clamp", () => { expect(clamp(9, 0, 5)).toBe(5) });\n',
    "pkg/__init__.py": "",
    "pkg/core.py": 'from .models import Item\nfrom . import utils\n\n\ndef total(items):\n    """Sum prices."""\n    s = 0\n    for i in items:\n        if i.price > 0 and i.ok:\n            s += utils.double(i.price)\n    return s\n',
    "pkg/models.py": "class Item:\n    def __init__(self, price, ok=True):\n        self.price = price\n        self.ok = ok\n",
    "pkg/utils.py": "def double(x):\n    return x * 2\n",
    "main.py": "from pkg.core import total\nfrom pkg.models import Item\n\nprint(total([Item(2)]))\n",
    "tests/test_core.py": "from pkg.core import total\n\n\ndef test_total():\n    assert total([]) == 0\n",
    "README.md": "# Demo\n\nA tiny project.\n\n## Usage\n\nRun main.py.\n",
    "config.json": '{"name": "demo", "version": 1}\n',
    "src/dup_one.ts": block("alpha"),
    "src/dup_two.ts": block("beta"),                      # same code as dup_one, different names: a duplicate group
}


def write_tree(root, files):
    import shutil
    if root.exists():
        shutil.rmtree(root)
    for path, text in files.items():
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


class Harness:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.repos = {}
        for name in ("inc", "full"):
            rid = conn.execute("INSERT INTO repos (url, full_name) VALUES (%s, %s) ON CONFLICT (url) DO UPDATE SET url = EXCLUDED.url RETURNING id",
                               (f"https://github.com/test/equiv-{name}", f"test/equiv-{name}")).fetchone()[0]
            conn.execute("DELETE FROM files WHERE repo_id = %s", (rid,))
            conn.execute("UPDATE repos SET status='pending', pipeline_version=NULL WHERE id = %s", (rid,))
            self.repos[name] = rid
        self.n = 0
        self.parsed: list[list[str]] = []
        orig = analysis_mod.parse_files

        def spy(root, paths, file_ids, progress):
            self.parsed.append(list(paths))
            return orig(root, paths, file_ids, progress)
        analysis_mod.parse_files = spy
        self._orig = orig

    def close(self):
        analysis_mod.parse_files = self._orig
        for rid in self.repos.values():
            conn.execute("DELETE FROM repos WHERE id = %s", (rid,))
        conn.execute("DELETE FROM embedding_cache WHERE model = %s", (EMB.name,))

    def run(self, which, files, requested="auto"):
        rid = self.repos[which]
        root = self.tmp / which
        write_tree(root, files)
        # status 'done': the schema allows only ONE queued/running job per repo, and this harness runs many in a row
        job = conn.execute("INSERT INTO analysis_jobs (repo_id, status) VALUES (%s, 'done') RETURNING id", (rid,)).fetchone()[0]
        status, version, _ = db.load_repo_state(conn, rid)
        self.n += 1
        res = analyze_checkout(conn, rid, job, root, f"sha{self.n}", progress=lambda s, p: None, embedder=EMB,
                               requested_mode=requested, previous_ready=status == "ready", previous_version=version)
        conn.execute("UPDATE repos SET status='ready', last_commit_sha=%s WHERE id=%s", (f"sha{self.n}", rid))
        return res

    def compare(self, files):
        """Full analysis of `files` into repo B, then assert repo A (incrementally updated) matches it table by table."""
        self.run("full", files, requested="full")
        a, b = snapshot(self.repos["inc"]), snapshot(self.repos["full"])
        assert set(a) == set(b)
        for table in a:
            assert a[table] == b[table], f"incremental != full in `{table}`"


def snapshot(rid):
    q = lambda sql, *p: conn.execute(sql, (rid, *p)).fetchall()  # noqa: E731
    r6 = lambda x: None if x is None else round(float(x), 6)       # noqa: E731
    snap = {}
    snap["files"] = sorted((p, lang, size, lines, h, t, ps, cl, cml, round(float(cr), 4) if cr is not None else None, tc, mc, fc, mod,
                            fin, fout, r6(pr), dl, r6(dr), ht, tf, r6(hs), churn)
                           for (p, lang, size, lines, h, t, ps, cl, cml, cr, tc, mc, fc, mod, fin, fout, pr, dl, dr, ht, tf, hs, churn)
                           in q("""SELECT path, language, size, lines, content_hash, is_test, parse_status, code_lines, comment_lines, comment_ratio,
                                          total_complexity, max_complexity, function_count, module, fan_in, fan_out, pagerank, dup_lines,
                                          dup_ratio, has_test, test_file, hotspot_score, churn FROM files WHERE repo_id = %s"""))
    snap["symbols"] = sorted(q("""SELECT f.path, s.idx, s.name, s.kind, s.start_line, s.end_line, s.complexity, s.max_nesting, s.param_count,
                                         s.parent_name, s.is_exported, s.has_doc FROM symbols s JOIN files f ON f.id = s.file_id WHERE s.repo_id = %s"""))
    snap["imports"] = sorted((p, i, sp, k, res, str(t), pkg, reason) for p, i, sp, k, res, t, pkg, reason in
                             q("""SELECT f.path, i.idx, i.specifier, i.kind, i.resolution, i.targets, i.package, i.reason
                                  FROM imports_raw i JOIN files f ON f.id = i.file_id WHERE i.repo_id = %s"""))
    snap["dependencies"] = sorted((a, b, str(k)) for a, b, k in q(
        """SELECT a.path, b.path, d.kinds FROM dependencies d JOIN files a ON a.id = d.from_file_id
           JOIN files b ON b.id = d.to_file_id WHERE d.repo_id = %s"""))
    snap["cycles"] = sorted(sorted(p for (p,) in conn.execute("SELECT path FROM files WHERE id = ANY(%s)", ([int(x) for x in ids],)))
                            for (ids,) in q("SELECT file_ids FROM dependency_cycles WHERE repo_id = %s"))
    snap["module_edges"] = sorted(q("SELECT from_module, to_module, edge_count FROM module_edges WHERE repo_id = %s"))
    snap["chunks"] = sorted((p, s, i, k, sym, a, b, ch, eh, emb) for p, s, i, k, sym, a, b, ch, eh, emb in
                            q("""SELECT path, strategy, idx, kind, symbol, start_line, end_line, content_hash, embed_hash,
                                        embedding IS NOT NULL FROM chunks WHERE repo_id = %s"""))
    groups = {}
    for gi, p, a, b in q("""SELECT d.group_idx, f.path, d.start_line, d.end_line FROM duplicate_blocks d
                            JOIN files f ON f.id = d.file_id WHERE d.repo_id = %s"""):
        groups.setdefault(gi, []).append((p, a, b))
    snap["duplicates"] = sorted(sorted(v) for v in groups.values())
    snap["tokens"] = sorted((p, n, hashlib.md5(bytes(h)).hexdigest(), hashlib.md5(bytes(ln)).hexdigest()) for p, n, h, ln in
                            q("SELECT f.path, t.n, t.hashes, t.lines FROM file_tokens t JOIN files f ON f.id = t.file_id WHERE f.repo_id = %s"))
    snap["contents"] = sorted((p, hashlib.md5(c.encode()).hexdigest()) for p, c in
                              q("SELECT f.path, c.content FROM file_contents c JOIN files f ON f.id = c.file_id WHERE f.repo_id = %s"))
    return snap


@pytest.fixture
def h(tmp_path):
    harness = Harness(tmp_path)
    yield harness
    harness.close()


def first_full(h, files):
    r = h.run("inc", files)
    assert r.mode == "full" and "first analysis" in r.reason
    h.parsed.clear()
    return r


def chunk_ids(rid, path):
    return sorted(i for (i,) in conn.execute("SELECT c.id FROM chunks c JOIN files f ON f.id = c.file_id WHERE f.repo_id=%s AND f.path=%s", (rid, path)))


def file_id(rid, path):
    row = conn.execute("SELECT id FROM files WHERE repo_id=%s AND path=%s", (rid, path)).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------------------------------------
def test_first_analysis_is_full_and_a_second_identical_one_is_a_cheap_incremental_noop(h):
    first_full(h, BASE)
    ids_before = {p: file_id(h.repos["inc"], p) for p in BASE}
    r = h.run("inc", BASE)
    assert r.mode == "incremental" and r.files_changed == 0 and r.files_reused == len(BASE) and h.parsed == [[]]
    assert ids_before == {p: file_id(h.repos["inc"], p) for p in BASE}      # rows untouched
    h.compare(BASE)


def test_modifying_one_file_reparses_only_that_file_and_matches_a_full_run(h):
    first_full(h, BASE)
    untouched = chunk_ids(h.repos["inc"], "pkg/models.py")
    files = {**BASE, "pkg/utils.py": "def double(x):\n    return x * 2\n\n\ndef triple(x):\n    if x:\n        return x * 3\n    return 0\n"}
    r = h.run("inc", files)
    assert r.mode == "incremental" and r.diff["modified"] == 1 and r.files_reused == len(BASE) - 1
    assert h.parsed == [["pkg/utils.py"]]                                       # nothing else was parsed again
    assert chunk_ids(h.repos["inc"], "pkg/models.py") == untouched              # unchanged file keeps its very chunk rows
    h.compare(files)


def test_adding_a_file_can_resolve_an_unchanged_files_previously_unresolved_import(h):
    first_full(h, BASE)
    assert conn.execute("SELECT resolution FROM imports_raw i JOIN files f ON f.id=i.file_id WHERE f.repo_id=%s AND f.path='src/app.ts' "
                        "AND i.specifier='./helpers'", (h.repos["inc"],)).fetchone()[0] == "unresolved"
    files = {**BASE, "src/helpers.ts": "export function nope() { return 1 }\n"}
    r = h.run("inc", files)
    assert r.diff["added"] == 1 and h.parsed == [["src/helpers.ts"]]            # app.ts was NOT re-parsed ...
    assert conn.execute("SELECT resolution, targets FROM imports_raw i JOIN files f ON f.id=i.file_id WHERE f.repo_id=%s AND f.path='src/app.ts' "
                        "AND i.specifier='./helpers'", (h.repos["inc"],)).fetchone() == ("internal", ["src/helpers.ts"])   # ... but its import resolves now
    h.compare(files)


def test_deleting_a_file_removes_its_rows_and_breaks_edges_into_it(h):
    first_full(h, BASE)
    files = {k: v for k, v in BASE.items() if k != "src/util.ts"}
    r = h.run("inc", files)
    assert r.diff["deleted"] == 1 and file_id(h.repos["inc"], "src/util.ts") is None
    assert conn.execute("SELECT count(*) FROM chunks WHERE repo_id=%s AND path='src/util.ts'", (h.repos["inc"],)).fetchone()[0] == 0
    h.compare(files)


def test_a_pure_rename_keeps_the_row_and_its_parse_results_but_rebuilds_chunks_for_the_new_path(h):
    first_full(h, BASE)
    fid = file_id(h.repos["inc"], "pkg/models.py")
    sym_ids = conn.execute("SELECT array_agg(id ORDER BY idx) FROM symbols WHERE file_id=%s", (fid,)).fetchone()[0]
    files = {("pkg/entities.py" if k == "pkg/models.py" else k): v for k, v in BASE.items()}
    r = h.run("inc", files)
    assert r.diff["renamed"] == 1 and r.diff["added"] == 0 and r.diff["deleted"] == 0
    assert file_id(h.repos["inc"], "pkg/entities.py") == fid                    # same row: moved, not recreated
    assert conn.execute("SELECT array_agg(id ORDER BY idx) FROM symbols WHERE file_id=%s", (fid,)).fetchone()[0] == sym_ids   # symbols reused
    assert "pkg/models.py" not in [p for batch in h.parsed for p in batch] and "pkg/entities.py" not in [p for batch in h.parsed for p in batch]
    assert all(p == "pkg/entities.py" for (p,) in conn.execute("SELECT path FROM chunks WHERE file_id=%s", (fid,)))   # headers carry the new path
    h.compare(files)


def test_rename_with_importers_updated_re_targets_the_edges(h):
    first_full(h, BASE)
    files = {k: v for k, v in BASE.items() if k != "src/util.ts"}
    files["src/shared/util.ts"] = BASE["src/util.ts"]
    files["src/app.ts"] = BASE["src/app.ts"].replace('"./util"', '"./shared/util"')
    files["src/lib/format.ts"] = BASE["src/lib/format.ts"].replace('"../util"', '"../shared/util"')
    files["src/util.test.ts"] = BASE["src/util.test.ts"]            # still imports ./util: now unresolved
    r = h.run("inc", files)
    assert r.diff["renamed"] == 1 and r.diff["modified"] == 2
    h.compare(files)


def test_rename_and_edit_at_once_is_delete_plus_add(h):
    first_full(h, BASE)
    files = {k: v for k, v in BASE.items() if k != "pkg/utils.py"}
    files["pkg/helpers.py"] = "def double(x):\n    return x * 2 + 0\n"
    r = h.run("inc", files)
    assert r.diff["renamed"] == 0 and r.diff["added"] == 1 and r.diff["deleted"] == 1
    h.compare(files)


def test_a_rename_that_changes_the_language_is_reparsed_not_reused(h):
    files0 = {**BASE, "src/legacy.js": "function legacy(a) { if (a) { return 1 } return 2 }\nmodule.exports = { legacy };\n"}
    first_full(h, files0)
    files = {k: v for k, v in files0.items() if k != "src/legacy.js"}
    files["src/legacy.ts"] = files0["src/legacy.js"]
    r = h.run("inc", files)
    assert r.diff["renamed"] == 0 and r.diff["added"] == 1 and "src/legacy.ts" in h.parsed[-1]
    h.compare(files)


def test_adding_a_test_file_changes_an_unchanged_sources_hotspot_inputs(h):
    first_full(h, BASE)
    files = {**BASE, "tests/test_models.py": "from pkg.models import Item\n\n\ndef test_item():\n    assert Item(1).ok\n"}
    h.run("inc", files)
    assert conn.execute("SELECT has_test, test_file FROM files WHERE repo_id=%s AND path='pkg/models.py'", (h.repos["inc"],)).fetchone() == (True, "tests/test_models.py")
    h.compare(files)


def test_a_new_copy_of_unchanged_code_forms_a_duplicate_group_using_stored_tokens(h):
    first_full(h, BASE)
    files = {**BASE, "src/dup_three.ts": block("gamma")}
    r = h.run("inc", files)
    assert h.parsed == [["src/dup_three.ts"]]
    groups = conn.execute("SELECT total_locations FROM duplicate_groups WHERE repo_id=%s", (h.repos["inc"],)).fetchall()
    assert (4,) in groups                    # rankApp (in app.ts), alpha, beta and the new gamma are one group of copies
    h.compare(files)


def test_creating_an_import_cycle_by_editing_one_file(h):
    first_full(h, BASE)
    files = {**BASE, "src/util.ts": 'import {fmt} from "./lib/format";\n' + BASE["src/util.ts"] + "export const label = fmt(1);\n"}
    h.run("inc", files)
    assert conn.execute("SELECT count(*) FROM dependency_cycles WHERE repo_id=%s", (h.repos["inc"],)).fetchone()[0] == 1
    h.compare(files)


def test_removing_a_whole_folder_and_adding_another_in_one_change(h):
    first_full(h, BASE)
    files = {k: v for k, v in BASE.items() if not k.startswith("src/lib/")}
    files["src/app.ts"] = BASE["src/app.ts"].replace('import {fmt} from "./lib/format";\n', "").replace("fmt(clamp(1, 0, 5))", "clamp(1, 0, 5)")
    files["docs/guide.md"] = "# Guide\n\n## Install\n\nRun pip install demo.\n"
    files["scripts/run.py"] = "import sys\n\n\ndef run():\n    return len(sys.argv)\n"
    h.run("inc", files)
    h.compare(files)


def test_three_incremental_runs_in_a_row_still_equal_a_fresh_full_analysis(h):
    first_full(h, BASE)
    files = dict(BASE)
    files["pkg/utils.py"] = "def double(x):\n    return x * 2\n\n\ndef half(x):\n    return x / 2\n"
    h.run("inc", files)
    files["src/new.ts"] = 'import {clamp} from "./util";\nexport const v = clamp(1, 0, 2);\n'
    h.run("inc", files)
    del files["main.py"]
    h.run("inc", files)
    h.compare(files)


@pytest.mark.parametrize("seed", range(6))
def test_random_edit_sequences_stay_equivalent(h, seed):
    rng = random.Random(seed)
    files = dict(BASE)
    first_full(h, files)
    for step in range(6):
        op = rng.choice(["modify", "add", "delete", "rename", "modify", "add_dup"])
        paths = sorted(p for p in files if p.endswith((".ts", ".py")))
        if op == "modify" and paths:
            p = rng.choice(paths)
            files[p] = files[p] + (f"\nexport const edit{step} = {step};\n" if p.endswith(".ts") else f"\n\ndef edit{step}():\n    return {step}\n")
        elif op == "add":
            files[f"gen/mod{step}.ts"] = f'import {{clamp}} from "../src/util";\nexport const g{step} = clamp({step}, 0, 9);\n'
        elif op == "add_dup":
            files[f"gen/copy{step}.ts"] = block(f"copy{step}")
        elif op == "delete" and len(paths) > 4:
            del files[rng.choice(paths)]
        elif op == "rename" and paths:
            p = rng.choice(paths)
            ext = p.rsplit(".", 1)[1]
            files[f"moved/m{step}.{ext}"] = files.pop(p)
        h.run("inc", files)
        if step in (2, 5):
            h.compare(files)                         # check mid-way and at the end
    h.compare(files)


# ---- when incremental must NOT be used, and self-healing ----------------------------------------------------
def test_a_full_run_is_forced_when_requested_or_when_the_previous_run_cannot_be_trusted(h):
    first_full(h, BASE)
    assert h.run("inc", BASE, requested="full").mode == "full"
    conn.execute("UPDATE repos SET status='failed' WHERE id=%s", (h.repos["inc"],))          # previous run did not complete
    r = h.run("inc", BASE)
    assert r.mode == "full" and "did not complete" in r.reason
    conn.execute("UPDATE repos SET pipeline_version=%s WHERE id=%s", (PIPELINE_VERSION - 1, h.repos["inc"]))
    r = h.run("inc", BASE)
    assert r.mode == "full" and "pipeline version" in r.reason
    assert h.run("inc", BASE).mode == "incremental"
    h.compare(BASE)


def test_a_supported_file_left_without_parse_results_is_healed_on_the_next_incremental_run(h):
    first_full(h, BASE)
    conn.execute("UPDATE files SET parse_status=NULL WHERE repo_id=%s AND path='pkg/utils.py'", (h.repos["inc"],))
    conn.execute("DELETE FROM symbols WHERE file_id=%s", (file_id(h.repos["inc"], "pkg/utils.py"),))
    r = h.run("inc", BASE)
    assert r.mode == "incremental" and h.parsed == [["pkg/utils.py"]]
    h.compare(BASE)


def test_vectors_are_only_computed_for_new_text(h):
    first_full(h, BASE)
    files = {**BASE, "pkg/utils.py": BASE["pkg/utils.py"] + "\n\ndef triple(x):\n    return x * 3\n"}
    r = h.run("inc", files)
    assert r.index and 0 < r.index.embedded <= 4          # a handful of changed chunks, not the whole repo
    assert r.index.chunks_total < 12                       # only the changed file was re-chunked
