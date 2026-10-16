"""Safe shallow clone of an untrusted public GitHub repo. Never executes repo code."""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import config

URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")


class CloneError(Exception):
    pass


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def clone(url: str, dest: Path) -> str:
    """Shallow-clone `url` into `dest`; return HEAD commit sha."""
    # Defence in depth: API validates too, but the worker never trusts its queue input.
    if not URL_RE.match(url) or url.rsplit("/", 1)[-1].startswith("-"):
        raise CloneError("URL rejected by allowlist")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    cmd = [
        "git",
        "-c", "core.hooksPath=/dev/null",   # never run hooks
        "-c", "core.symlinks=false",        # symlinks checked out as plain files
        "-c", "protocol.allow=never",
        "-c", "protocol.https.allow=always",
        "clone", "--depth", "1", "--single-branch", "--no-tags",
        "--no-recurse-submodules", "--quiet", "--", url, str(dest),
    ]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + config.CLONE_TIMEOUT_S
    while proc.poll() is None:
        if time.monotonic() > deadline:
            proc.kill()
            proc.wait()
            shutil.rmtree(dest, ignore_errors=True)
            raise CloneError(f"clone timed out after {config.CLONE_TIMEOUT_S}s")
        if dest.exists() and dir_size(dest) > config.MAX_REPO_BYTES:
            proc.kill()
            proc.wait()
            shutil.rmtree(dest, ignore_errors=True)
            raise CloneError(f"repo exceeds {config.MAX_REPO_BYTES // (1024 * 1024)} MB limit")
        time.sleep(0.5)
    if proc.returncode != 0:
        err = (proc.stderr.read() or b"").decode(errors="replace").strip()[-300:]
        shutil.rmtree(dest, ignore_errors=True)
        raise CloneError(f"git clone failed: {err or 'unknown error'}")

    sha = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return sha
