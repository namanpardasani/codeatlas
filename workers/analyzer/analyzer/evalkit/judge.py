"""LLM-as-judge with a written rubric. Scores are cached by everything that influences them, so a re-run is free
and a changed rubric/model cannot silently reuse old verdicts."""
import hashlib
import json
import re

from .. import config
from ..llm import get_llm
from ..llm.types import Delta, Message, Usage, estimate_tokens
from .answers import evidence_text
from .schema import Dataset

RUBRIC_VERSION = "rubric-v1"

RUBRIC_MD = """# Grading rubric (used by the LLM judge AND by the human spot-check)

Grade each answer on three independent dimensions, 0-2. Judge only what is written; do not reward length or style.

**correctness** - does the answer say what the ground-truth notes say?
- 2: contains the key facts of the notes and nothing that contradicts them
- 1: partly right: misses a key fact, or is vague, or adds a wrong minor detail
- 0: wrong, off-topic, or says nothing useful

**groundedness** - is every claim backed by the provided code excerpts?
- 2: every claim is visible in the excerpts
- 1: mostly supported, but one or two claims go beyond the excerpts (general knowledge, guesses)
- 0: key claims are not in the excerpts (invented functions, behaviour, files)

**citation_validity** - do the cited passages (the [C#] labels and files named) actually support the sentences they are attached to?
- 2: citations point at the passages that support the claims
- 1: some citations are wrong, missing for key claims, or only loosely related
- 0: citations are wrong or absent for the answer's main claims
- if the answer has no citations at all because it correctly refused: grade 2; if it makes claims with no citations: grade 0

A refusal ("I couldn't find this in the repo.") is correct only for questions marked unanswerable.
"""

PROMPT = """You are a strict grader of answers about a code repository. Grade the ANSWER using the rubric. Output ONLY one JSON object.

RUBRIC (scores 0, 1 or 2):
- correctness: does the answer say what the GROUND TRUTH says? 2 = key facts present and nothing contradicting; 1 = partly right or vague; 0 = wrong or useless.
- groundedness: is every claim in the answer visible in the EXCERPTS? 2 = all claims supported; 1 = one or two claims go beyond the excerpts; 0 = key claims are not in the excerpts.
- citation_validity: do the cited labels/files support the sentences they are attached to? 2 = yes; 1 = some wrong or missing; 0 = wrong or absent.

QUESTION: {question}

GROUND TRUTH (written by a human who knows the repo): {notes}
CORRECT FILES: {files}

EXCERPTS the answerer was given:
{evidence}

ANSWER TO GRADE:
{answer}

Respond with exactly this JSON and nothing else:
{{"correctness": 0, "groundedness": 0, "citation_validity": 0, "unsupported_claims": ["short quote of each claim not in the excerpts"], "reason": "one sentence"}}"""

DIMS = ("correctness", "groundedness", "citation_validity")


def judge_llm(env: dict | None = None):
    """EVAL_JUDGE_PROVIDER / EVAL_JUDGE_MODEL / EVAL_JUDGE_API_KEY / EVAL_JUDGE_BASE_URL select the judge; they
    default to the answering model's LLM_* settings (which means the model grades its own work: see the limits)."""
    import os
    e = dict(os.environ if env is None else env)
    for k in ("PROVIDER", "MODEL", "API_KEY", "BASE_URL"):
        if e.get(f"EVAL_JUDGE_{k}"):
            e[f"LLM_{k}"] = e[f"EVAL_JUDGE_{k}"]
    return get_llm(e)


def parse_verdict(text: str) -> dict | None:
    """Lenient: small models wrap JSON in prose or fences. Accept the first {...} that has the three scores 0-2."""
    for m in re.finditer(r"\{.*?\}(?=\s*(?:$|```|\n\n))|\{.*\}", text, re.S):
        try:
            d = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(d, dict) and all(isinstance(d.get(k), int) and not isinstance(d.get(k), bool) and 0 <= d[k] <= 2 for k in DIMS):
            return {**{k: d[k] for k in DIMS}, "unsupported_claims": [str(x)[:200] for x in (d.get("unsupported_claims") or [])][:8],
                    "reason": str(d.get("reason", ""))[:300]}
    return None


def cache_key(model: str, q, answer: str, evidence: str) -> str:
    h = hashlib.sha256()
    for part in (RUBRIC_VERSION, model, q.question, q.answer_notes, ",".join(q.files), answer, evidence):
        h.update(part.encode())
        h.update(b"\x00")
    return h.hexdigest()


def _ask(llm, prompt: str) -> tuple[str, int, int]:
    text, tin, tout = "", 0, 0
    for ev in llm.stream([Message("user", prompt)], max_tokens=300, temperature=0.0):
        if isinstance(ev, Delta):
            text += ev.text
        elif isinstance(ev, Usage):
            tin, tout = ev.input_tokens, ev.output_tokens
    return text, tin or estimate_tokens(prompt), tout or estimate_tokens(text)


def judge_item(conn, llm, q, item: dict) -> dict:
    """Deterministic cases need no judge: a refusal is right exactly when the question is unanswerable."""
    if item["status"] == "error":
        return {"skipped": "answer generation failed"}
    if item["refused"]:
        s = 2 if not q.answerable else 0
        return {"correctness": s, "groundedness": 2, "citation_validity": 2, "rule": "refusal", "unsupported_claims": [],
                "reason": "refused an unanswerable question" if not q.answerable else "refused an answerable question"}
    if not q.answerable:
        return {"correctness": 0, "groundedness": 0, "citation_validity": 0, "rule": "answered-unanswerable",
                "unsupported_claims": [item["answer"][:200]], "reason": "answered a question the repo cannot answer"}
    ev = evidence_text(conn, item["retrieved"])
    key = cache_key(llm.model, q, item["answer"], ev)
    row = conn.execute("SELECT verdict FROM eval_judge_cache WHERE cache_key = %s", (key,)).fetchone()
    if row:
        return {**row[0], "cached": True}
    prompt = PROMPT.format(question=q.question, notes=q.answer_notes, files=", ".join(q.files), evidence=ev[:9000],
                           answer=item["answer"][:3000])
    verdict, tin, tout = None, 0, 0
    for attempt in range(2):
        text, a, b = _ask(llm, prompt if attempt == 0 else prompt + "\n\nYour previous reply was not valid JSON. Reply with the JSON object only.")
        tin, tout = tin + a, tout + b
        verdict = parse_verdict(text)
        if verdict:
            break
    if not verdict:
        return {"parse_failed": True}                      # counted and reported, never silently scored
    conn.execute("INSERT INTO eval_judge_cache (cache_key, judge_model, rubric_version, verdict, tokens_in, tokens_out) "
                 "VALUES (%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT DO NOTHING",
                 (key, llm.model, RUBRIC_VERSION, json.dumps(verdict), tin, tout))
    return {**verdict, "cached": False, "tokens": [tin, tout]}


def run_judge(conn, llm, ds: Dataset, answer_items: list[dict], on_progress=None) -> tuple[dict, list[dict]]:
    by_id = {q.id: q for q in ds.questions}
    out = []
    for n, it in enumerate(answer_items, 1):
        v = judge_item(conn, llm, by_id[it["id"]], it)
        out.append({"id": it["id"], "repo": it["repo"], **v})
        if on_progress:
            on_progress(n, len(answer_items), it["id"])
    return summarise_judge(out, by_id), out


def summarise_judge(verdicts: list[dict], by_id: dict) -> dict:
    from . import metrics
    scored = [v for v in verdicts if "correctness" in v]
    answered = [v for v in scored if v.get("rule") != "refusal"]     # answers actually produced (incl. answering the unanswerable)
    s = {"n": len(verdicts), "scored": len(scored), "parse_failed": sum(1 for v in verdicts if v.get("parse_failed")),
         "judge_calls_cached": sum(1 for v in verdicts if v.get("cached")), "rubric": RUBRIC_VERSION}
    for d in DIMS:
        s[f"mean_{d}"] = metrics.mean(v[d] for v in scored) if scored else None
        s[f"{d}_full_marks"] = metrics.rate([v[d] == 2 for v in scored])
    # hallucination = an answer that went beyond the evidence; computed on answers actually produced
    s["hallucination_rate_any"] = metrics.rate([v["groundedness"] < 2 for v in answered])
    s["hallucination_rate_serious"] = metrics.rate([v["groundedness"] == 0 for v in answered])
    s["n_answers_judged"] = len(answered)
    return s
