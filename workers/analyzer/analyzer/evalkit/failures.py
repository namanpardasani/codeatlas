"""Failure analysis: turn per-question results into the categories the improvement work is driven by."""
from collections import Counter, defaultdict

RETRIEVAL_MISS = "retrieval miss"
WRONG_CHUNKING = "wrong chunking"
HALLUCINATION = "hallucination"
BAD_CITATION = "bad citation"
IMPORT_RESOLUTION = "import-resolution error"
OVER_REFUSAL = "over-refusal"
OTHER = "other"


def retrieval_failures(items: list[dict], file_has_chunks: dict[str, bool] | None = None) -> list[dict]:
    """A question fails retrieval when no target is in the top-k. If the right FILE was retrieved but not the right
    symbol, the chunk boundaries are the problem (wrong chunking); if the file never shows up, it is a retrieval miss."""
    out = []
    for it in items:
        if it["first_rank"] is not None:
            continue
        cat = WRONG_CHUNKING if it.get("file_in_top_k") else RETRIEVAL_MISS
        out.append({"id": it["id"], "category": cat, "top": [t["path"] for t in it["top"]]})
    return out


def answer_failures(answers: list[dict], verdicts: list[dict], retrieval_ok: dict[str, bool]) -> list[dict]:
    v_by = {v["id"]: v for v in verdicts}
    out = []
    for a in answers:
        v = v_by.get(a["id"], {})
        if a["status"] == "error":
            out.append({"id": a["id"], "category": OTHER, "why": "generation error"})
        elif a["refused"] and a["answerable"]:
            out.append({"id": a["id"], "category": RETRIEVAL_MISS if not retrieval_ok.get(a["id"], True) else OVER_REFUSAL,
                        "why": "refused an answerable question"})
        elif not a["refused"] and not a["answerable"]:
            out.append({"id": a["id"], "category": HALLUCINATION, "why": "answered an unanswerable question"})
        elif "groundedness" in v and v["groundedness"] < 2 and v.get("rule") != "refusal":
            out.append({"id": a["id"], "category": HALLUCINATION, "why": "; ".join(v.get("unsupported_claims") or []) or v.get("reason", "")})
        elif "citation_validity" in v and v["citation_validity"] < 2 and v.get("rule") != "refusal":
            out.append({"id": a["id"], "category": BAD_CITATION, "why": v.get("reason", "")})
        elif "correctness" in v and v["correctness"] < 2 and v.get("rule") != "refusal":
            out.append({"id": a["id"], "category": RETRIEVAL_MISS if not retrieval_ok.get(a["id"], True) else OTHER,
                        "why": v.get("reason", "")})
    return out


def graph_failures(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        for e, d in (it.get("false_negative_diagnosis") or {}).items():
            out.append({"repo": it["repo"], "edge": e, "category": IMPORT_RESOLUTION if d["cause"] == "import-resolution" else OTHER,
                        "why": d["cause"], "detail": d.get("imports")})
        for a, b in it.get("false_positives") or []:
            out.append({"repo": it["repo"], "edge": f"{a} -> {b}", "category": OTHER, "why": "spurious edge (not in ground truth)"})
    return out


def tally(failures: list[dict]) -> dict[str, int]:
    return dict(Counter(f["category"] for f in failures).most_common())


def group(failures: list[dict]) -> dict[str, list[dict]]:
    g = defaultdict(list)
    for f in failures:
        g[f["category"]].append(f)
    return dict(g)
