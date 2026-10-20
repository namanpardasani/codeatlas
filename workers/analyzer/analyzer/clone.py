"""Safe bounded-history clone of an untrusted public GitHub repo. Never executes repo code."""
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


class LimitError(CloneError):
    """Clone stopped by the time or size limit (the caller may retry with less history)."""


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


GIT_ENV_KEYS = ("PATH", "HOME")


def git_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in GIT_ENV_KEYS if k in os.environ}
    env.setdefault("PATH", "/usr/bin:/bin")
    env.setdefault("HOME", "/tmp")
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
    return env


def build_clone_cmd(url: str, dest: Path, history: bool, filtered: bool) -> list[str]:
    """history=True: last HISTORY_MAX_COMMITS commits (bounded, for churn); False: just HEAD.
    filtered=True: partial clone without file contents of old commits (history needs names only)."""
    depth = config.HISTORY_MAX_COMMITS if history else 1
    return [
        "git",
        "-c", "core.hooksPath=/dev/null",   # never run hooks
        "-c", "core.symlinks=false",        # symlinks checked out as plain files
        "-c", "protocol.allow=never",
        "-c", "protocol.https.allow=always",
        "clone", f"--depth={depth}", "--single-branch", "--no-tags",
        *(["--filter=blob:none"] if filtered and history else []),
        "--no-recurse-submodules", "--quiet", "--", url, str(dest),
    ]


def _run_clone(cmd: list[str], dest: Path) -> None:
    proc = subprocess.Popen(cmd, env=git_env(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.monotonic() + config.CLONE_TIMEOUT_S
    while proc.poll() is None:
        if time.monotonic() > deadline:
            proc.kill()
            proc.wait()
            shutil.rmtree(dest, ignore_errors=True)
            raise LimitError(f"clone timed out after {config.CLONE_TIMEOUT_S}s")
        if dest.exists() and dir_size(dest) > config.MAX_REPO_BYTES:
            proc.kill()
            proc.wait()
            shutil.rmtree(dest, ignore_errors=True)
            raise LimitError(f"repo exceeds {config.MAX_REPO_BYTES // (1024 * 1024)} MB limit")
        time.sleep(0.5)
    if proc.returncode != 0:
        err = (proc.stderr.read() or b"").decode(errors="replace").strip()[-300:]
        shutil.rmtree(dest, ignore_errors=True)
        raise CloneError(f"git clone failed: {err or 'unknown error'}")


def clone(url: str, dest: Path, history: bool = True) -> str:
    """Clone `url` into `dest` (bounded history if `history`); return the HEAD commit sha."""
    # Defence in depth: API validates too, but the worker never trusts its queue input.
    if not URL_RE.fullmatch(url) or url.rsplit("/", 1)[-1].startswith(("-", ".")):   # fullmatch: `$` would accept a trailing newline
        raise CloneError("URL rejected by allowlist")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        _run_clone(build_clone_cmd(url, dest, history, filtered=True), dest)
    except LimitError:
        raise
    except CloneError as e:
        if not history:
            raise
        # server without partial-clone support: retry once with full objects for the bounded history
        _run_clone(build_clone_cmd(url, dest, history, filtered=False), dest)

    return subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        env=git_env(), capture_output=True, text=True, check=True,
    ).stdout.strip()
