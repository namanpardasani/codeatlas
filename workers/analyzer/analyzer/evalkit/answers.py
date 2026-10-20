"""Generate answers with the real chat pipeline (same retrieval, prompt and citation verifier users get)."""
from .. import config
from ..rag.pipeline import answer
from . import metrics
from .schema import Dataset

CLIENT_KEY = "eval-harness"


def lift_caps_if_free(llm) -> None:
    """The per-client daily caps protect a public demo from abuse. An evaluation of 50+ questions would hit them,
    and free/local providers cost nothing, so lift them for those. Paid providers keep their caps."""
    if not getattr(llm, "paid", False):
        config.LLM_DAILY_REQUESTS = config.LLM_DAILY_TOKENS = config.LLM_GLOBAL_DAILY_TOKENS = 10**9


def run_one(conn, embedder, llm, repo_id: int, question: str, reranker=None, min_similarity=None) -> dict:
    final, error = None, None
    for ev in answer(conn, embedder, llm, repo_id, question, client_key=CLIENT_KEY, reranker=reranker,
                    min_similarity=min_similarity):
        if ev["type"] == "final":
            final = ev
        elif ev["type"] == "error":
            error = ev
    if final is None:
        return {"status": "error", "error": error, "answer": "", "citations": [], "removed": [], "retrieved": []}
    return final


def evidence_text(conn, retrieved: list[dict], max_chars: int = 1500) -> str:
    """The code the model actually saw (labels C1.. as in its prompt), for the judge and the human grader."""
    parts = []
    for r in retrieved:
        row = conn.execute("SELECT content FROM chunks WHERE id = %s", (r["chunk_id"],)).fetchone()
        body = (row[0] if row else "")[:max_chars]
        parts.append(f"[{r['label']}] {r['path']}:{r['start_line']}-{r['end_line']}\n{body}")
    return "\n\n".join(parts)


def run_answers(conn, embedder, llm, ds: Dataset, ids: dict[str, int], reranker=None, only: set[str] | None = None,
                on_progress=None, min_similarity=None) -> tuple[dict, list[dict]]:
    lift_caps_if_free(llm)
    items = []
    for n, q in enumerate(ds.questions, 1):
        if only and q.id not in only:
            continue
        f = run_one(conn, embedder, llm, ids[q.repo], q.question, reranker, min_similarity)
        refused = f["status"] == "not_found"
        model_cites = [c for c in f.get("citations", []) if not c.get("inferred")]
        items.append({
            "id": q.id, "repo": q.repo, "question": q.question, "answerable": q.answerable, "status": f["status"],
            "refused": refused, "answer": f.get("answer", ""), "citations": f.get("citations", []),
            "removed_sentences": f.get("removed", []), "issues": f.get("issues", []),
            "retrieved": f.get("retrieved") or f.get("closest") or [], "llm_called": f.get("llm_called", False),
            "model": f.get("model"), "usage": f.get("usage"), "error": f.get("error"),
            "citation_correctness": metrics.citation_correctness([c["path"] for c in model_cites], q.files) if q.answerable else None,
        })
        if on_progress:
            on_progress(n, len(ds.questions), q.id, f["status"])
    return summarise_answers(items), items


def summarise_answers(items: list[dict]) -> dict:
    ok = [i for i in items if i["status"] != "error"]
    answered = [i for i in ok if not i["refused"]]
    prec = [i["citation_correctness"]["precision"] for i in answered if i["citation_correctness"] and i["citation_correctness"]["precision"] is not None]
    rec = [i["citation_correctness"]["recall"] for i in answered if i["citation_correctness"] and i["citation_correctness"]["recall"] is not None]
    return {
        "n": len(items), "errors": len(items) - len(ok), "answered": len(answered),
        **metrics.refusal_stats([(i["answerable"], i["refused"]) for i in ok]),
        "verifier_removed_sentences_rate": metrics.rate([bool(i["removed_sentences"]) for i in answered]),
        "citation_file_precision": metrics.mean(prec) if prec else None,
        "citation_file_recall": metrics.mean(rec) if rec else None,
        "answers_without_model_citation": metrics.rate([i["citation_correctness"]["n_cited"] == 0 for i in answered if i["citation_correctness"]]),
    }
