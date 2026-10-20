import os
from pathlib import Path

import pytest

from analyzer import config
from analyzer.inventory import InventoryError, build_inventory, is_test_path


def write(root: Path, rel: str, content: bytes | str = "x = 1\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode())


def test_basic_inventory_and_language(tmp_path):
    write(tmp_path, "src/app.ts", "const a = 1;\nconst b = 2;\n")
    write(tmp_path, "main.py", "print('hi')")
    recs = {r.path: r for r in build_inventory(tmp_path)}
    assert recs["src/app.ts"].language == "typescript"
    assert recs["src/app.ts"].lines == 2
    assert recs["main.py"].lines == 1  # no trailing newline still counts
    assert len(recs["main.py"].content_hash) == 64


def test_skips_vendored_binary_generated_and_large(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_FILE_BYTES", 100)
    write(tmp_path, "node_modules/lib/index.js")
    write(tmp_path, "dist/out.js")
    write(tmp_path, "img.png", b"\x89PNG\x00\x00binary")
    write(tmp_path, "bundle.min.js")
    write(tmp_path, "package-lock.json", "{}")
    write(tmp_path, "big.py", "x" * 500)
    write(tmp_path, "keep.py")
    assert [r.path for r in build_inventory(tmp_path)] == ["keep.py"]


def test_honors_gitignore(tmp_path):
    write(tmp_path, ".gitignore", "secret.py\ngenerated/\n*.tmp\n")
    write(tmp_path, "secret.py")
    write(tmp_path, "generated/a.py")
    write(tmp_path, "a.tmp")
    write(tmp_path, "ok.py")
    paths = {r.path for r in build_inventory(tmp_path)}
    assert "ok.py" in paths and "secret.py" not in paths
    assert not any(p.startswith("generated/") for p in paths) and "a.tmp" not in paths


def test_symlinks_are_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    write(outside, "leak.py", "secret")
    repo = tmp_path / "repo"
    repo.mkdir()
    write(repo, "real.py")
    os.symlink(outside / "leak.py", repo / "link.py")
    os.symlink(outside, repo / "linkdir")
    assert [r.path for r in build_inventory(repo)] == ["real.py"]


def test_file_count_limit_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_FILES", 2)
    for i in range(3):
        write(tmp_path, f"f{i}.py")
    with pytest.raises(InventoryError):
        build_inventory(tmp_path)


@pytest.mark.parametrize("path,expected", [
    ("tests/test_a.py", True), ("src/foo.test.ts", True), ("src/__tests__/x.js", True),
    ("pkg/foo_test.go", True), ("src/foo.ts", False), ("src/latest.py", False),
])
def test_is_test_path(path, expected):
    assert is_test_path(path) is expected


def test_total_entry_cap_stops_repos_of_millions_of_tiny_or_ignored_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_WALK_ENTRIES", 5)
    for i in range(6):
        write(tmp_path, f"x{i}.lock", "")          # skipped files still count towards the cap
    with pytest.raises(InventoryError):
        build_inventory(tmp_path)


def test_hostile_gitignore_is_bounded(tmp_path):
    write(tmp_path, ".gitignore", "a\n" * 200_000)   # far above the size cap: ignored, never compiled
    write(tmp_path, "ok.py")
    assert "ok.py" in {r.path for r in build_inventory(tmp_path)}
    write(tmp_path, ".gitignore", "*.py\n" + "x" * 1000 + "\n")   # an overlong line is dropped, the rest applies
    assert "ok.py" not in {r.path for r in build_inventory(tmp_path)}
