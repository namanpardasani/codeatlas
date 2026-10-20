import pytest

from analyzer.clone import CloneError, clone


@pytest.mark.parametrize("url", [
    "http://github.com/a/b",
    "https://gitlab.com/a/b",
    "https://github.com.evil.com/a/b",
    "https://github.com/a/b/c",
    "https://github.com/a/-upload-pack=x",
    "--upload-pack=touch /tmp/pwn",
    "file:///etc/passwd",
    "ssh://git@github.com/a/b",
    "https://127.0.0.1/a/b",
    "https://user:pw@github.com/a/b",
    "https://github.com/a/b\n--config=x",
    "https://github.com/a/b\n",          # `$` in a regex would accept a trailing newline
    "https://github.com/a/.hidden",
])
def test_rejects_non_allowlisted_urls(url, tmp_path):
    with pytest.raises(CloneError):
        clone(url, tmp_path / "dest")


def test_clone_command_is_hardened_and_history_bounded():
    from pathlib import Path
    from analyzer import config
    from analyzer.clone import build_clone_cmd
    cmd = build_clone_cmd("https://github.com/a/b", Path("/tmp/x"), history=True, filtered=True)
    for flag in ("core.hooksPath=/dev/null", "core.symlinks=false", "protocol.allow=never",
                 "--no-recurse-submodules", "--single-branch", "--no-tags"):
        assert flag in " ".join(cmd)
    assert f"--depth={config.HISTORY_MAX_COMMITS}" in cmd and "--filter=blob:none" in cmd
    head_only = build_clone_cmd("https://github.com/a/b", Path("/tmp/x"), history=False, filtered=True)
    assert "--depth=1" in head_only and "--filter=blob:none" not in head_only
    assert cmd[-3] == "--" and cmd[-2] == "https://github.com/a/b"  # url after `--`: never an option
