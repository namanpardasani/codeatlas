"""Manual spot-check sheet: N random answers for a human to grade with the SAME rubric as the judge, then an
honest judge-vs-human agreement report. The sheet deliberately does not contain the judge's scores (anchoring)."""
import csv
import random
from pathlib import Path

from . import metrics
from .judge import DIMS

COLUMNS = ["sample_no", "question_id", "repo", "question", "ground_truth_notes", "correct_files", "answer",
           "cited_files", "retrieved_files", "your_correctness_0_2", "your_groundedness_0_2",
           "your_citation_validity_0_2", "your_notes"]


def sample_ids(items: list[dict], n: int = 15, seed: int = 20261020) -> list[dict]:
    """Seeded random sample of answers the model actually wrote (refusals are mechanical, not worth a human's time).
    Fewer than n answers -> all of them (never padded)."""
    pool = sorted((i for i in items if i["status"] in ("answered", "partial") and not i["refused"]), key=lambda i: i["id"])
    return random.Random(seed).sample(pool, min(n, len(pool)))


def write_sheet(path: str | Path, picked: list[dict], by_id: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for n, it in enumerate(picked, 1):
            q = by_id[it["id"]]
            w.writerow([n, q.id, q.repo, q.question, q.answer_notes, "; ".join(q.files), it["answer"],
                        "; ".join(sorted({c["path"] for c in it["citations"]})),
                        "; ".join(sorted({r["path"] for r in it["retrieved"]})), "", "", "", ""])


def read_grades(path: str | Path) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vals = {}
            for d, col in zip(DIMS, ("your_correctness_0_2", "your_groundedness_0_2", "your_citation_validity_0_2")):
                raw = (row.get(col) or "").strip()
                if raw in ("0", "1", "2"):
                    vals[d] = int(raw)
            if len(vals) == 3:
                out[row["question_id"]] = vals
    return out


def compare(human: dict[str, dict[str, int]], judged: list[dict]) -> dict:
    by_id = {v["id"]: v for v in judged if "correctness" in v}
    ids = sorted(i for i in human if i in by_id)
    rep: dict = {"n_graded_by_human": len(human), "n_compared": len(ids)}
    for d in DIMS:
        a = [by_id[i][d] for i in ids]
        b = [human[i][d] for i in ids]
        ag = metrics.agreement(a, b)
        rep[d] = {**ag, "judge_mean": metrics.mean(a) if a else None, "human_mean": metrics.mean(b) if b else None,
                  "bias_judge_minus_human": (metrics.mean(a) - metrics.mean(b)) if a else None,
                  "pearson": metrics.pearson(a, b),
                  "judge_more_lenient_on": [i for i, x, y in zip(ids, a, b) if x > y],
                  "judge_harsher_on": [i for i, x, y in zip(ids, a, b) if x < y]}
    return rep
