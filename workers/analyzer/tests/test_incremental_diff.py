"""classify(): added / modified / deleted / renamed, by content hash."""
import random

import pytest

from analyzer.incremental import classify


def h(text):  # stand-in content hash
    return f"hash:{text}"


def tree(**files):
    return {p.replace("__", "/").replace("_dot_", "."): h(c) for p, c in files.items()}


def test_no_changes():
    t = {"a.py": h("1"), "b.py": h("2")}
    d = classify(t, dict(t))
    assert d.unchanged == ["a.py", "b.py"] and d.changed_count == 0 and not d.deleted and not d.renamed


def test_modified_added_deleted():
    old = {"keep.py": h("k"), "edit.py": h("v1"), "gone.py": h("g")}
    new = {"keep.py": h("k"), "edit.py": h("v2"), "fresh.py": h("f")}
    d = classify(old, new)
    assert (d.unchanged, d.modified, d.added, d.deleted, d.renamed) == (["keep.py"], ["edit.py"], ["fresh.py"], ["gone.py"], [])
    assert d.reparse == ["edit.py", "fresh.py"]


def test_a_move_with_identical_content_is_a_rename_not_delete_plus_add():
    d = classify({"src/old_name.py": h("body")}, {"src/new_name.py": h("body")})
    assert d.renamed == [("src/old_name.py", "src/new_name.py")] and not d.added and not d.deleted
    assert d.reparse == [] and d.rechunk == ["src/new_name.py"]       # nothing to parse, but the path is in every chunk header


def test_moving_a_whole_folder_pairs_files_by_name():
    old = {"lib/a.py": h("A"), "lib/b.py": h("B"), "lib/sub/c.py": h("C")}
    new = {"core/a.py": h("A"), "core/b.py": h("B"), "core/sub/c.py": h("C")}
    d = classify(old, new)
    assert d.renamed == [("lib/a.py", "core/a.py"), ("lib/b.py", "core/b.py"), ("lib/sub/c.py", "core/sub/c.py")]
    assert not d.added and not d.deleted


def test_identical_files_are_paired_by_name_then_folder_similarity():
    """Many empty __init__.py: the pairing must follow the folder move, not an arbitrary order."""
    e = h("")
    old = {"pkg/a/__init__.py": e, "pkg/b/__init__.py": e, "pkg/c/__init__.py": e}
    new = {"lib/a/__init__.py": e, "lib/b/__init__.py": e, "lib/c/__init__.py": e}
    d = classify(old, new)
    assert d.renamed == [("pkg/a/__init__.py", "lib/a/__init__.py"), ("pkg/b/__init__.py", "lib/b/__init__.py"),
                         ("pkg/c/__init__.py", "lib/c/__init__.py")]


def test_a_copy_is_an_addition_not_a_rename():
    d = classify({"a.py": h("same")}, {"a.py": h("same"), "copy_of_a.py": h("same")})
    assert d.added == ["copy_of_a.py"] and d.unchanged == ["a.py"] and not d.renamed


def test_rename_and_edit_together_is_delete_plus_add():
    d = classify({"old.py": h("v1")}, {"new.py": h("v2")})
    assert d.deleted == ["old.py"] and d.added == ["new.py"] and not d.renamed


def test_swapping_the_contents_of_two_files_is_two_modifications():
    d = classify({"a.py": h("A"), "b.py": h("B")}, {"a.py": h("B"), "b.py": h("A")})
    assert d.modified == ["a.py", "b.py"] and not d.renamed


def test_more_identical_files_deleted_than_added_leaves_the_rest_deleted():
    e = h("")
    d = classify({"a/x.py": e, "b/x.py": e, "c/x.py": e}, {"a/x.py": e})
    assert d.unchanged == ["a/x.py"] and d.deleted == ["b/x.py", "c/x.py"] and not d.renamed


def test_one_rename_among_other_changes():
    old = {"a.py": h("1"), "b.py": h("2"), "c.py": h("3"), "d.py": h("4")}
    new = {"a.py": h("1"), "b2.py": h("2"), "c.py": h("3-edited"), "e.py": h("5")}
    d = classify(old, new)
    assert d.renamed == [("b.py", "b2.py")] and d.modified == ["c.py"] and d.deleted == ["d.py"] and d.added == ["e.py"]
    assert d.unchanged == ["a.py"] and d.summary() == {"added": 1, "modified": 1, "deleted": 1, "renamed": 1, "unchanged": 1}


def test_case_only_rename_is_a_rename():
    d = classify({"README.md": h("x")}, {"readme.md": h("x")})
    assert d.renamed == [("README.md", "readme.md")]


def test_result_does_not_depend_on_dict_order():
    rng = random.Random(4)
    old = {f"d{i % 4}/f{i}.py": h(str(i % 7)) for i in range(40)}
    new = {f"e{i % 5}/f{i}.py": h(str((i + 2) % 9)) for i in range(40)}
    base = classify(old, new)
    for _ in range(5):
        o, n = list(old.items()), list(new.items())
        rng.shuffle(o), rng.shuffle(n)
        assert classify(dict(o), dict(n)) == base


def test_each_path_lands_in_exactly_one_bucket():
    rng = random.Random(9)
    for _ in range(30):
        old = {f"p{rng.randrange(25)}.py": h(str(rng.randrange(6))) for _ in range(20)}
        new = {f"p{rng.randrange(25)}.py": h(str(rng.randrange(6))) for _ in range(20)}
        d = classify(old, new)
        old_seen = d.unchanged + d.modified + d.deleted + [o for o, _ in d.renamed]
        new_seen = d.unchanged + d.modified + d.added + [n for _, n in d.renamed]
        assert sorted(old_seen) == sorted(old) and sorted(new_seen) == sorted(new)          # a partition, nothing lost or doubled
        for o, n in d.renamed:
            assert old[o] == new[n]


def test_huge_identical_groups_do_not_blow_up():
    e = h("")
    old = {f"a/f{i}.py": e for i in range(400)}
    new = {f"b/f{i}.py": e for i in range(400)}
    d = classify(old, new)
    assert len(d.renamed) == 400 and not d.added and not d.deleted
