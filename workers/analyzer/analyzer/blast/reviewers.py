"""Suggested reviewers: people who most often and most recently changed the code this change impacts.

score(author) = sum over impacted files f (the change's files and its top blast radius) of
                impact(f) x sum over the author's commits touching f of exp(-age / HALF_LIFE)
Recent work counts more (a commit a year ago is worth ~0.25 of one today at a 180-day half-life). The change's own
author and bots (dependabot, renovate, github-actions...) are excluded; only code and test files count. Only names are shown; emails are used to tell people apart, never displayed.
"""
import math
import re
from dataclasses import dataclass

from ..parsing import supported

from .history import Commit
from .impact import ImpactResult

HALF_LIFE_DAYS = 180
BOT = re.compile(r"\[bot\]|\bbot@|dependabot|renovate|github-actions|greenkeeper|snyk", re.I)
TOP_FILES = 15


@dataclass
class Reviewer:
    name: str
    score: float
    commits: int
    files: list[str]

    def reason(self) -> str:
        shown = ", ".join(self.files[:3]) + (f" and {len(self.files) - 3} more" if len(self.files) > 3 else "")
        return f"{self.commits} recent commit(s) to {shown}"


def suggest_reviewers(impact: ImpactResult, history: list[Commit], now: int, exclude_email: str | None = None,
                      limit: int = 3) -> list[Reviewer]:
    weight = {}
    for f in [x for x in impact.files if supported(x.path_str)][:TOP_FILES]:   # code and tests, not changelogs
        weight[f.path_str] = max(weight.get(f.path_str, 0.0), f.score)
    by: dict[str, dict] = {}
    lam = math.log(2) / (HALF_LIFE_DAYS * 86400)
    for c in history:
        if (exclude_email and c.email == exclude_email) or BOT.search(c.email) or BOT.search(c.name or ""):
            continue
        touched = [p for p in c.files if p in weight]
        if not touched:
            continue
        rec = math.exp(-lam * max(0, now - c.time))
        d = by.setdefault(c.email, {"name": c.name or c.email.split("@")[0], "score": 0.0, "commits": 0, "files": {}})
        d["commits"] += 1
        for p in touched:
            d["score"] += weight[p] * rec
            d["files"][p] = d["files"].get(p, 0) + 1
    ranked = sorted(by.values(), key=lambda d: -d["score"])[:limit]
    return [Reviewer(d["name"], round(d["score"], 3), d["commits"],
                     [p for p, _ in sorted(d["files"].items(), key=lambda kv: -kv[1])]) for d in ranked if d["score"] > 0]
