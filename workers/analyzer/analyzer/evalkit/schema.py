"""Loading and validating the hand-written ground truth. Nothing here invents questions: an incomplete file
produces a list of problems, not defaults."""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TARGET_QUESTIONS = 50
TARGET_REPOS = (3, 5)


@dataclass
class Question:
    id: str
    repo: str
    question: str
    answer_notes: str
    files: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    answerable: bool = True
    tags: list[str] = field(default_factory=list)


@dataclass
class Dataset:
    questions: list[Question]
    sha256: str
    path: str


@dataclass
class GraphTruth:
    repo: str
    files: list[str]
    edges: list[tuple[str, str]]


def _read(path: str | Path) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data, hashlib.sha256(raw).hexdigest()


def load_questions(path: str | Path) -> tuple[Dataset, list[str]]:
    """Returns (dataset of the entries that are usable, problems found). Entries with problems are still listed
    in `problems` so the author can fix them; unusable ones are left out of the dataset, never repaired."""
    data, digest = _read(path)
    problems: list[str] = []
    out: list[Question] = []
    seen: set[str] = set()
    for i, q in enumerate(data.get("questions") or []):
        where = f"questions[{i}] ({q.get('id', '?') if isinstance(q, dict) else '?'})"
        if not isinstance(q, dict):
            problems.append(f"{where}: must be a mapping")
            continue
        bad = [k for k in ("id", "repo", "question", "answer_notes") if not str(q.get(k) or "").strip()]
        if bad:
            problems.append(f"{where}: missing {', '.join(bad)}")
        answerable = q.get("answerable", True)
        files = [str(f) for f in (q.get("files") or [])]
        if answerable and not files:
            problems.append(f"{where}: answerable question without any correct file in `files`")
        if not answerable and files:
            problems.append(f"{where}: answerable: false but `files` is not empty")
        dup = str(q.get("id")) in seen
        if dup:
            problems.append(f"{where}: duplicate id")
        seen.add(str(q.get("id")))
        if bad or dup or (answerable and not files) or (not answerable and files):
            continue
        out.append(Question(str(q["id"]), str(q["repo"]).lower(), str(q["question"]).strip(), str(q["answer_notes"]).strip(),
                            files, [str(s) for s in (q.get("symbols") or [])], bool(answerable),
                            [str(t) for t in (q.get("tags") or [])]))
    return Dataset(out, digest, str(path)), problems


def completeness(ds: Dataset) -> list[str]:
    """What is still missing relative to the plan (about 50 questions over 3-5 repos)."""
    repos = {q.repo for q in ds.questions}
    gaps = []
    if len(ds.questions) < TARGET_QUESTIONS:
        gaps.append(f"{len(ds.questions)} usable questions, plan is about {TARGET_QUESTIONS}: {TARGET_QUESTIONS - len(ds.questions)} missing")
    if len(repos) < TARGET_REPOS[0]:
        gaps.append(f"{len(repos)} repos, plan is {TARGET_REPOS[0]}-{TARGET_REPOS[1]}")
    if len(repos) > TARGET_REPOS[1]:
        gaps.append(f"{len(repos)} repos, plan is at most {TARGET_REPOS[1]}")
    if ds.questions and not any(not q.answerable for q in ds.questions):
        gaps.append("no unanswerable questions (answerable: false): refusal behaviour cannot be measured")
    return gaps


def load_graph_truth(path: str | Path) -> tuple[list[GraphTruth], str, list[str]]:
    data, digest = _read(path)
    problems: list[str] = []
    out: list[GraphTruth] = []
    for i, r in enumerate(data.get("repos") or []):
        where = f"repos[{i}] ({r.get('repo', '?') if isinstance(r, dict) else '?'})"
        if not isinstance(r, dict) or not r.get("repo") or not r.get("files"):
            problems.append(f"{where}: needs `repo` and `files` (the verified set of files)")
            continue
        files = [str(f) for f in r["files"]]
        edges = []
        for e in r.get("edges") or []:
            if not (isinstance(e, (list, tuple)) and len(e) == 2):
                problems.append(f"{where}: edge {e!r} must be [from, to]")
                continue
            a, b = str(e[0]), str(e[1])
            for p in (a, b):
                if p not in files:
                    problems.append(f"{where}: edge endpoint {p} is not in `files`")
            edges.append((a, b))
        out.append(GraphTruth(str(r["repo"]).lower(), files, edges))
    return out, digest, problems
