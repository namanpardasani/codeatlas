"""Helpers that build throwaway git repos with controlled authors and dates."""
import os
import subprocess
from pathlib import Path

DAY = 86400
T0 = 1_735_689_600  # 2025-01-01T00:00:00Z


def git(repo: Path, *args: str, env_extra: dict | None = None):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", **(env_extra or {})}
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def init(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")


def commit(repo: Path, when: int, author: str, files: dict[str, str]):
    for name, content in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        git(repo, "add", name)
    date = f"{when} +0000"
    git(repo, "-c", f"user.name={author}", "-c", f"user.email={author}@x.dev", "commit", "-q", "-m", "c",
        "--allow-empty", env_extra={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
