"""The harness end to end on the fixture repo (hash embedder, scripted LLM): schema validation, relevance by lines,
the retrieval runner, answer + judge + cache, spot-check sheet, graph evaluation, failure categories."""
import json

import pytest
import yaml

from analyzer import db, indexing
from analyzer.embeddings import HashEmbedder
from analyzer.evalkit import answers as ans_mod, failures, graph_eval, judge, retrieval, schema, spotcheck, store
from analyzer.evalkit.relevance import covered_by, resolve_targets
from analyzer.llm.types import Delta, Usage
from analyzer.inventory import FileRecord

from fixture_repo import FILES, LANG, source_files

try:
    conn = db.connect()
except Exception:  # noqa: BLE001
    conn = None
needs_db = pytest.mark.skipif(conn is None, reason="Postgres not available")
EMB = HashEmbedder()
REPO = "test/evalrepo"

QUESTIONS = {"questions": [
    {"id": "t1", "repo": REPO, "question": "how does retry with exponential backoff work?",
     "answer_notes": "retry_with_backoff doubles the delay after each failed attempt", "files": ["src/retry.py"],
     "symbols": ["retry_with_backoff"]},
    {"id": "t2", "repo": REPO, "question": "how is a password verified against the stored hash?",
     "answer_notes": "verify_password compares a sha256 digest", "files": ["src/auth.py"]},
    {"id": "t3", "repo": REPO, "question": "where is the kubernetes operator reconciled?",
     "answer_notes": "nowhere: this repo has no kubernetes code", "answerable": False},
]}


@pytest.fixture
def repo(tmp_path):
    rid = conn.execute("INSERT INTO repos (url, full_name, status) VALUES ('https://github.com/test/evalrepo', %s, 'ready') "
                       "ON CONFLICT (url) DO UPDATE SET status = 'ready' RETURNING id", (REPO,)).fetchone()[0]
    ids = db.save_files(conn, rid, "sha", [FileRecord(p, LANG[p.rsplit(".", 1)[-1]], len(t), t.count("\n"), "h", False)
                                           for p, t in FILES.items()])
    srcs = source_files()
    from analyzer.parsing import parse_source
    db.save_parse_results(conn, rid, {ids[p]: parse_source(p, t.encode()) for p, t in FILES.items() if not p.endswith(".md")})
    indexing.index_repo(conn, EMB, rid, ids, srcs)
    path = tmp_path / "q.yaml"
    path.write_text(yaml.safe_dump(QUESTIONS))
    yield rid, ids, path
    conn.execute("DELETE FROM repos WHERE id = %s", (rid,))
    conn.execute("DELETE FROM embedding_cache WHERE model = %s", (EMB.name,))
    conn.execute("DELETE FROM eval_runs WHERE label LIKE 'pytest%%'")


# ---- schema ---------------------------------------------------------------------------------------------
def test_schema_reports_problems_instead_of_inventing(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(yaml.safe_dump({"questions": [
        {"id": "a", "repo": "x/y", "question": "q?", "answer_notes": "n", "files": ["f.py"]},
        {"id": "a", "repo": "x/y", "question": "dup", "answer_notes": "n", "files": ["f.py"]},
        {"id": "b", "repo": "x/y", "question": "", "answer_notes": "n", "files": ["f.py"]},
        {"id": "c", "repo": "x/y", "question": "q", "answer_notes": "n"},
        {"id": "d", "repo": "x/y", "question": "q", "answer_notes": "n", "answerable": False, "files": ["f.py"]},
    ]}))
    ds, problems = schema.load_questions(p)
    assert [q.id for q in ds.questions] == ["a"]                      # only the valid one survives, nothing repaired
    text = "\n".join(problems)
    assert "duplicate id" in text and "missing question" in text and "without any correct file" in text and "answerable: false but" in text
    gaps = "\n".join(schema.completeness(ds))
    assert "49 missing" in gaps and "1 repos" in gaps and "no unanswerable" in gaps


def test_dataset_hash_changes_with_content(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(yaml.safe_dump(QUESTIONS))
    h1 = schema.load_questions(p)[0].sha256
    p.write_text(yaml.safe_dump(QUESTIONS) + "# edit\n")
    assert schema.load_questions(p)[0].sha256 != h1


def test_graph_truth_validation(tmp_path):
    p = tmp_path / "g.yaml"
    p.write_text(yaml.safe_dump({"repos": [{"repo": "A/B", "files": ["a.py", "b.py"], "edges": [["a.py", "b.py"], ["a.py", "zzz.py"], ["x"]]},
                                           {"repo": "c/d"}]}))
    truths, _, problems = schema.load_graph_truth(p)
    assert truths[0].repo == "a/b" and truths[0].edges[0] == ("a.py", "b.py")
    assert any("zzz.py is not in" in x for x in problems) and any("must be [from, to]" in x for x in problems)
    assert any("needs `repo` and `files`" in x for x in problems)


# ---- relevance --------------------------------------------------------------------------------------------
@needs_db
def test_relevance_is_decided_on_lines_so_every_chunking_is_scored_the_same(repo):
    rid, _, path = repo
    ds, _ = schema.load_questions(path)
    q1, q2 = ds.questions[0], ds.questions[1]
    t1, p1 = resolve_targets(conn, rid, q1)
    assert not p1 and t1[0].label == "retry_with_backoff"
    (file, s, e), = t1[0].spans
    assert file == "src/retry.py" and s <= 5 <= e
    assert covered_by("src/retry.py", 1, 2, t1) == frozenset()               # imports only: right file, wrong lines
    assert covered_by("src/retry.py", e, e + 50, t1) == frozenset({0})       # overlap at the boundary counts
    assert covered_by("src/auth.py", s, e, t1) == frozenset()                # wrong file
    t2, _ = resolve_targets(conn, rid, q2)
    assert covered_by("src/auth.py", 7, 8, t2) == frozenset({0})             # file target: any line


@needs_db
def test_missing_files_and_symbols_are_reported(repo):
    rid, _, _ = repo
    q = schema.Question("z", REPO, "q", "n", ["src/nope.py"], ["ghost"])
    _, problems = resolve_targets(conn, rid, q)
    assert any("src/nope.py" in p for p in problems) and any("ghost" in p for p in problems)


# ---- retrieval runner -------------------------------------------------------------------------------------
@needs_db
def test_retrieval_runner_scores_variants_and_stores_the_run(repo):
    rid, _, path = repo
    ds, _ = schema.load_questions(path)
    ids, problems = retrieval.check_ground_truth(conn, ds)
    assert not problems and ids == {REPO: rid}
    variants = [retrieval.Variant("ast", "keyword"), retrieval.Variant("ast", "hybrid"), retrieval.Variant("fixed", "keyword")]
    summary, items = retrieval.run_retrieval(conn, EMB, None, ds, ids, variants)
    assert set(summary) == {"ast/keyword", "ast/hybrid", "fixed/keyword"}
    assert summary["ast/hybrid"]["n"] == 2                                   # the unanswerable question is not retrieved
    assert summary["ast/keyword"]["recall@10"] == 1.0 and summary["ast/keyword"]["mrr"] > 0.5
    first = {i["id"]: i for i in items["ast/keyword"]}
    assert first["t1"]["first_rank"] == 1 and first["t1"]["top"][0]["relevant"] is True
    assert first["t1"]["file_in_top_k"] is True
    run_id = store.save_run(conn, "retrieval", "pytest", ds.sha256, retrieval.run_config(variants, EMB.name, None), summary, items,
                            write_file=False)
    back = store.load_run(conn, run_id)
    assert back["summary"]["ast/hybrid"]["mrr"] == summary["ast/hybrid"]["mrr"] and back["dataset_hash"] == ds.sha256


@needs_db
def test_rerank_variant_uses_the_scorer_and_can_change_the_order(repo):
    rid, _, path = repo
    ds, _ = schema.load_questions(path)
    ids, _ = retrieval.check_ground_truth(conn, ds)
    worst_first = lambda q, docs: list(range(len(docs)))            # noqa: E731  reverses the ranking
    best_first = lambda q, docs: [len(docs) - i for i in range(len(docs))]  # noqa: E731  keeps it
    v = retrieval.Variant("ast", "hybrid", True)
    s_keep, _ = retrieval.run_variant(conn, EMB, best_first, ds, ids, v)
    s_flip, _ = retrieval.run_variant(conn, EMB, worst_first, ds, ids, v)
    assert s_keep["mrr"] > s_flip["mrr"]


@needs_db
def test_unembedded_chunks_are_detected(repo):
    rid, _, path = repo
    ds, _ = schema.load_questions(path)
    ids, _ = retrieval.check_ground_truth(conn, ds)
    conn.execute("UPDATE chunks SET embedding = NULL, embed_model = NULL WHERE repo_id = %s AND strategy = 'fixed'", (rid,))
    assert (REPO, "fixed") in retrieval.unembedded(conn, ids, {"fixed"})


# ---- answers + judge ------------------------------------------------------------------------------------
class JudgeLLM:
    name, model, paid = "scripted-judge", "judge-1", False

    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def stream(self, messages, **kw):
        self.calls += 1
        yield Delta(self.replies.pop(0))
        yield Usage(100, 20)


class AnswerLLM:
    name, model, paid = "scripted-answerer", "answerer-1", False

    def __init__(self, fn):
        self.fn = fn

    def stream(self, messages, **kw):
        yield Delta(self.fn(messages[-1].content))
        yield Usage(10, 10)


def good_answer(prompt: str) -> str:
    import re
    label = re.search(r"^\[(C\d+)\] src/retry\.py", prompt, re.M)
    if label:
        return f"`retry_with_backoff` waits twice as long after each failure [{label.group(1)}]."
    return "I couldn't find this in the repo."


@needs_db
def test_answers_run_and_judge_with_cache(repo):
    rid, _, path = repo
    ds, _ = schema.load_questions(path)
    ids, _ = retrieval.check_ground_truth(conn, ds)
    _, items = ans_mod.run_answers(conn, EMB, AnswerLLM(good_answer), ds, ids, only={"t1"}, min_similarity=0.0)
    s3, items3 = ans_mod.run_answers(conn, EMB, AnswerLLM(good_answer), ds, ids, only={"t3"})     # production threshold
    summary = s3
    by = {i["id"]: i for i in items + items3}
    assert by["t1"]["status"] in ("answered", "partial") and not by["t1"]["refused"]
    assert by["t1"]["citation_correctness"]["precision"] == 1.0                   # cited the right file
    assert by["t3"]["refused"] is True and summary["correct_refusal_rate"] == 1.0
    q = {x.id: x for x in ds.questions}

    j = JudgeLLM(['Sure! {"correctness": 2, "groundedness": 2, "citation_validity": 1, "unsupported_claims": [], "reason": "ok"}'])
    v1 = judge.judge_item(conn, j, q["t1"], by["t1"])
    assert (v1["correctness"], v1["groundedness"], v1["citation_validity"]) == (2, 2, 1) and j.calls == 1 and not v1["cached"]
    v2 = judge.judge_item(conn, j, q["t1"], by["t1"])
    assert v2["cached"] is True and j.calls == 1                                  # cache hit: no second call
    assert judge.judge_item(conn, JudgeLLM(["{}"]), q["t3"], by["t3"])["correctness"] == 2    # right refusal: by rule
    # a different answer must not reuse the cached verdict
    other = dict(by["t1"], answer=by["t1"]["answer"] + " Also it retries forever.")
    j2 = JudgeLLM(['{"correctness": 1, "groundedness": 0, "citation_validity": 2, "unsupported_claims": ["retries forever"], "reason": "x"}'])
    assert judge.judge_item(conn, j2, q["t1"], other)["groundedness"] == 0 and j2.calls == 1
    conn.execute("DELETE FROM eval_judge_cache WHERE judge_model IN ('judge-1')")


@needs_db
def test_judge_parse_failure_is_counted_not_scored(repo):
    rid, _, path = repo
    ds, _ = schema.load_questions(path)
    ids, _ = retrieval.check_ground_truth(conn, ds)
    _, items = ans_mod.run_answers(conn, EMB, AnswerLLM(good_answer), ds, ids, only={"t1"}, min_similarity=0.0)
    j = JudgeLLM(["I think it is pretty good", "still not json"])
    s, verdicts = judge.run_judge(conn, j, ds, items)
    assert verdicts[0]["parse_failed"] is True and j.calls == 2                  # one retry, then give up
    assert s["parse_failed"] == 1 and s["scored"] == 0 and s["mean_correctness"] is None


def test_verdict_parser_accepts_fences_and_rejects_out_of_range():
    ok = judge.parse_verdict('```json\n{"correctness": 1, "groundedness": 2, "citation_validity": 0, "unsupported_claims": ["a"], "reason": "r"}\n```')
    assert ok["correctness"] == 1 and ok["unsupported_claims"] == ["a"]
    assert judge.parse_verdict('{"correctness": 3, "groundedness": 2, "citation_validity": 0}') is None
    assert judge.parse_verdict('{"correctness": true, "groundedness": 2, "citation_validity": 0}') is None
    assert judge.parse_verdict("no json here") is None


def test_judge_summary_hallucination_rates():
    by = {k: schema.Question(k, "r", "q", "n", ["f"]) for k in "abcd"}
    v = [{"id": "a", "correctness": 2, "groundedness": 2, "citation_validity": 2},
         {"id": "b", "correctness": 1, "groundedness": 1, "citation_validity": 2},
         {"id": "c", "correctness": 0, "groundedness": 0, "citation_validity": 0},
         {"id": "d", "correctness": 2, "groundedness": 2, "citation_validity": 2, "rule": "refusal"}]
    s = judge.summarise_judge(v, by)
    assert s["n_answers_judged"] == 3 and s["hallucination_rate_any"] == pytest.approx(2 / 3)
    assert s["hallucination_rate_serious"] == pytest.approx(1 / 3)


# ---- spot-check -----------------------------------------------------------------------------------------
def _item(i, refused=False):
    return {"id": f"q{i:02d}", "status": "not_found" if refused else "answered", "refused": refused, "answer": f"answer {i}",
            "citations": [{"path": "a.py"}], "retrieved": [{"path": "b.py"}]}


def test_spotcheck_sample_is_seeded_random_and_skips_refusals():
    items = [_item(i, refused=(i % 5 == 0)) for i in range(40)]
    a, b = spotcheck.sample_ids(items, 15), spotcheck.sample_ids(items, 15)
    assert [x["id"] for x in a] == [x["id"] for x in b] and len(a) == 15 and not any(x["refused"] for x in a)
    assert [x["id"] for x in a] != [x["id"] for x in spotcheck.sample_ids(items, 15, seed=1)]
    assert len(spotcheck.sample_ids(items[:4], 15)) == 3                         # never padded


def test_spotcheck_sheet_hides_judge_scores_and_agreement_is_computed(tmp_path):
    ds_q = {f"q{i:02d}": schema.Question(f"q{i:02d}", "r/x", "why?", "notes", ["a.py"]) for i in range(6)}
    picked = [_item(i) for i in range(6)]
    sheet = tmp_path / "s.csv"
    spotcheck.write_sheet(sheet, picked, ds_q)
    text = sheet.read_text()
    assert "judge" not in text.lower() and "your_correctness_0_2" in text
    import csv
    rows = list(csv.DictReader(open(sheet)))
    for r, (c, g, ci) in zip(rows, [(2, 2, 2), (1, 2, 2), (0, 1, 0), (2, 2, 1), (1, 1, 1), (2, 0, 2)]):
        r["your_correctness_0_2"], r["your_groundedness_0_2"], r["your_citation_validity_0_2"] = str(c), str(g), str(ci)
    rows[5]["your_notes"] = "left blank rows are ignored below"
    rows.append({**rows[0], "question_id": "q99", "your_correctness_0_2": ""})          # incomplete row ignored
    with open(sheet, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    human = spotcheck.read_grades(sheet)
    assert len(human) == 6
    judged = [{"id": f"q{i:02d}", "correctness": c, "groundedness": g, "citation_validity": ci}
              for i, (c, g, ci) in enumerate([(2, 2, 2), (2, 2, 2), (1, 1, 1), (2, 2, 1), (1, 1, 1), (2, 2, 2)])]
    rep = spotcheck.compare(human, judged)
    assert rep["n_compared"] == 6 and rep["correctness"]["exact"] == pytest.approx(4 / 6)
    assert rep["correctness"]["bias_judge_minus_human"] > 0                         # this judge is more lenient
    assert rep["correctness"]["judge_more_lenient_on"] == ["q01", "q02"]


# ---- graph ----------------------------------------------------------------------------------------------
@needs_db
def test_graph_eval_precision_recall_and_diagnosis(repo):
    rid, ids, _ = repo
    conn.execute("INSERT INTO dependencies (repo_id, from_file_id, to_file_id, kinds) VALUES (%s,%s,%s,'[\"import\"]'), (%s,%s,%s,'[\"import\"]')",
                 (rid, ids["src/retry.py"], ids["src/auth.py"], rid, ids["src/auth.py"], ids["src/pool.py"]))
    conn.execute("INSERT INTO imports_raw (repo_id, file_id, idx, specifier, kind, line, resolution, reason) VALUES (%s,%s,0,'./config','import',1,'unresolved','no such file')",
                 (rid, ids["src/pool.py"]))
    truth = schema.GraphTruth(REPO, ["src/retry.py", "src/auth.py", "src/pool.py", "src/config.ts"],
                              [("src/retry.py", "src/auth.py"), ("src/pool.py", "src/config.ts")])
    micro, items = graph_eval.run_graph(conn, [truth])
    assert micro["tp"] == 1 and micro["predicted"] == 2 and micro["truth"] == 2
    assert micro["precision"] == 0.5 and micro["recall"] == 0.5
    it = items[0]
    assert it["false_positives"] == [("src/auth.py", "src/pool.py")]
    diag = it["false_negative_diagnosis"]["src/pool.py -> src/config.ts"]
    assert diag["cause"] == "import-resolution" and diag["imports"][0]["resolution"] == "unresolved"
    f = failures.graph_failures(items)
    assert failures.tally(f) == {failures.IMPORT_RESOLUTION: 1, failures.OTHER: 1}


# ---- failure categories ---------------------------------------------------------------------------------
def test_retrieval_failure_categories():
    items = [{"id": "ok", "first_rank": 2, "top": []},
             {"id": "miss", "first_rank": None, "file_in_top_k": False, "top": [{"path": "x.py"}]},
             {"id": "chunk", "first_rank": None, "file_in_top_k": True, "top": [{"path": "a.py"}]}]
    f = failures.retrieval_failures(items)
    assert {x["id"]: x["category"] for x in f} == {"miss": failures.RETRIEVAL_MISS, "chunk": failures.WRONG_CHUNKING}


def test_answer_failure_categories():
    a = lambda i, **k: {"id": i, "status": "answered", "refused": False, "answerable": True, **k}   # noqa: E731
    answers = [a("r1", refused=True, status="not_found"), a("r2", refused=True, status="not_found"),
               a("u", answerable=False), a("h"), a("c"), a("w"), a("fine")]
    verdicts = [{"id": "h", "correctness": 2, "groundedness": 0, "citation_validity": 2, "unsupported_claims": ["x"]},
                {"id": "c", "correctness": 2, "groundedness": 2, "citation_validity": 0, "reason": "wrong lines"},
                {"id": "w", "correctness": 0, "groundedness": 2, "citation_validity": 2, "reason": "wrong"},
                {"id": "fine", "correctness": 2, "groundedness": 2, "citation_validity": 2}]
    f = {x["id"]: x["category"] for x in failures.answer_failures(answers, verdicts, {"r1": False, "r2": True, "w": True})}
    assert f == {"r1": failures.RETRIEVAL_MISS, "r2": failures.OVER_REFUSAL, "u": failures.HALLUCINATION,
                 "h": failures.HALLUCINATION, "c": failures.BAD_CITATION, "w": failures.OTHER}
