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
])
def test_rejects_non_allowlisted_urls(url, tmp_path):
    with pytest.raises(CloneError):
        clone(url, tmp_path / "dest")
