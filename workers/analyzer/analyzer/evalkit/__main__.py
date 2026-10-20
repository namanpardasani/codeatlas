"""Evaluation CLI.  uv run python -m analyzer.evalkit <command> --help

  validate    check eval/questions.yaml (+ graph truth) against the analysed repos; list what is missing
  retrieval   recall@k / MRR for every retrieval variant
  answers     generate answers with the real chat pipeline
  judge       LLM-judge the answers (use --estimate first)
  spotcheck   write the CSV of random answers for a human to grade
  agreement   compare the human grades with the judge
  graph       dependency-edge precision/recall against hand-verified edges
  failures    categorise what went wrong
  report      Markdown from stored runs
"""
import argparse
import json
import sys
from pathlib import Path

from .. import db
from . import answers as answers_mod
from . import failures as fail_mod
from . import graph_eval, judge as judge_mod, report, retrieval, schema, spotcheck, store

ROOT = Path(__file__).resolve().parents[4]
Q_DEFAULT = ROOT / "eval" / "questions.yaml"
G_DEFAULT = ROOT / "eval" / "graph_truth.yaml"


def load_ds(path: str):
    if not Path(path).exists():
        raise SystemExit(f"{path} does not exist. Write it first (format: eval/README.md).")
    ds, problems = schema.load_questions(path)
    return ds, problems


def cmd_validate(a, conn) -> int:
    bad = 0
    print(f"== questions: {a.questions}")
    if not Path(a.questions).exists():
        print("MISSING: the file does not exist (format: eval/README.md)")
        bad += 1
    else:
        ds, problems = load_ds(a.questions)
        ids, repo_problems = retrieval.check_ground_truth(conn, ds)
        problems += repo_problems
        print(f"{len(ds.questions)} usable questions over {len({q.repo for q in ds.questions})} repos "
              f"({sum(1 for q in ds.questions if not q.answerable)} unanswerable), sha256 {ds.sha256[:12]}")
        for p in problems:
            print(f"PROBLEM: {p}")
        for g in schema.completeness(ds):
            print(f"INCOMPLETE: {g}")
        bad += len(problems) + len(schema.completeness(ds))
    print(f"== graph truth: {a.graph}")
    if not Path(a.graph).exists():
        print("MISSING: the file does not exist (optional until Step 4; format: eval/README.md)")
    else:
        truths, _, problems = schema.load_graph_truth(a.graph)
        print(f"{len(truths)} repos, {sum(len(t.edges) for t in truths)} verified edges")
        for p in problems:
            print(f"PROBLEM: {p}")
        bad += len(problems)
    print("OK" if not bad else f"{bad} issue(s)")
    return 1 if bad else 0


def _ready(a, conn):
    ds, problems = load_ds(a.questions)
    ids, repo_problems = retrieval.check_ground_truth(conn, ds)
    problems += repo_problems
    if problems or not ds.questions:
        for p in problems:
            print(f"PROBLEM: {p}", file=sys.stderr)
        raise SystemExit("Fix the problems above (run `validate`) before evaluating. Nothing was run.")
    if (gaps := schema.completeness(ds)) and not a.allow_incomplete:
        for g in gaps:
            print(f"INCOMPLETE: {g}", file=sys.stderr)
        raise SystemExit("The question set is incomplete; add --allow-incomplete to run on what exists "
                         "(results will be labelled with the real n).")
    return ds, ids


def cmd_retrieval(a, conn) -> int:
    ds, ids = _ready(a, conn)
    names = {v.name: v for v in retrieval.ALL_VARIANTS}
    variants = retrieval.ALL_VARIANTS if a.variants == "all" else [names[n] for n in a.variants.split(",")]
    from ..embeddings import get_embedder
    embedder = get_embedder()
    if embedder is None:
        raise SystemExit("embedding model unavailable")
    missing = retrieval.unembedded(conn, ids, {v.chunking for v in variants if v.mode != "keyword"})
    if missing:
        if not a.embed_missing:
            raise SystemExit(f"chunks without vectors {missing}. Re-run with --embed-missing (local, free, slow for the fixed baseline).")
        from ..indexing import embed_pending
        for (repo, chunking), _ in missing.items():
            print(f"embedding {chunking} chunks of {repo} ...")
            embed_pending(conn, embedder, ids[repo], (chunking,), None, 3600)
    scorer, rname = None, None
    if any(v.rerank for v in variants):
        from ..rag.rerank import CrossEncoderReranker
        enc = CrossEncoderReranker()
        scorer, rname = enc.scores, enc.name
    summary, items = retrieval.run_retrieval(conn, embedder, scorer, ds, ids, variants)
    cfg = retrieval.run_config(variants, embedder.name, rname)
    cfg["n_questions"] = sum(1 for q in ds.questions if q.answerable)
    run_id = store.save_run(conn, "retrieval", a.label, ds.sha256, cfg, summary, items)
    print(f"retrieval run {run_id} ({a.label or 'unlabelled'}) saved\n")
    print(report.retrieval_table(summary))
    return 0


def _llm():
    from ..llm import get_llm
    return get_llm()


def cmd_answers(a, conn) -> int:
    ds, ids = _ready(a, conn)
    from ..embeddings import get_embedder
    llm = _llm()
    reranker = None
    if a.rerank:
        from ..rag.rerank import CrossEncoderReranker
        reranker = CrossEncoderReranker().scores
    summary, items = answers_mod.run_answers(conn, get_embedder(), llm, ds, ids, reranker,
                                             set(a.only.split(",")) if a.only else None,
                                             lambda n, t, i, s: print(f"[{n}/{t}] {i}: {s}", flush=True))
    cfg = {"llm": llm.name, "model": llm.model, "rerank": a.rerank, "n_questions": len(items)}
    run_id = store.save_run(conn, "answers", a.label, ds.sha256, cfg, summary, items)
    print(f"\nanswers run {run_id} saved\n" + report.answers_block(summary, None))
    return 0


def cmd_judge(a, conn) -> int:
    run = store.load_run(conn, a.answers) if a.answers else store.latest_run(conn, "answers")
    if not run:
        raise SystemExit("no answers run yet: run `answers` first")
    ds, _ = load_ds(a.questions)
    by_id = {q.id: q for q in ds.questions}
    if run["dataset_hash"] != ds.sha256:
        print("WARNING: the questions file changed since that answers run; judging against the CURRENT notes.", file=sys.stderr)
    to_judge = [i for i in run["items"] if i["status"] != "error" and not i["refused"] and by_id[i["id"]].answerable]
    est_in = sum(len(judge_mod.PROMPT) // 3.5 + len(i["answer"]) // 3.5 + 1800 for i in to_judge)
    est_out = 120 * len(to_judge)
    llm = judge_mod.judge_llm()
    print(f"judge: {llm.name}/{llm.model} (paid={llm.paid}); {len(to_judge)} answers need a verdict "
          f"(refusals are scored by rule, cached verdicts are free)")
    print(f"estimate: ~{int(est_in):,} input + ~{est_out:,} output tokens for a full uncached pass")
    if a.estimate:
        return 0
    if llm.paid and not a.yes:
        raise SystemExit("This judge bills money. Re-run with --yes after you have seen the estimate above.")
    summary, verdicts = judge_mod.run_judge(conn, llm, ds, run["items"], lambda n, t, i: print(f"[{n}/{t}] {i}", flush=True))
    summary["judge_model"] = llm.model
    summary["same_model_as_answerer"] = llm.model == run["config"].get("model")
    run_id = store.save_run(conn, "judge", a.label, ds.sha256, {"answers_run": run["id"], "judge": llm.model, "rubric": judge_mod.RUBRIC_VERSION},
                            summary, verdicts)
    print(f"\njudge run {run_id} saved\n" + report.answers_block(run["summary"], summary))
    return 0


def cmd_spotcheck(a, conn) -> int:
    run = store.load_run(conn, a.answers) if a.answers else store.latest_run(conn, "answers")
    ds, _ = load_ds(a.questions)
    picked = spotcheck.sample_ids(run["items"], a.n, a.seed)
    spotcheck.write_sheet(a.out, picked, {q.id: q for q in ds.questions})
    Path(a.out).with_name("RUBRIC.md").write_text(judge_mod.RUBRIC_MD)
    print(f"wrote {a.out} ({len(picked)} answers from answers run {run['id']}, seed {a.seed}) and RUBRIC.md beside it.\n"
          "Fill the three your_* columns with 0, 1 or 2 using RUBRIC.md, then run `agreement`.")
    return 0


def cmd_agreement(a, conn) -> int:
    jr = store.load_run(conn, a.judge) if a.judge else store.latest_run(conn, "judge")
    human = spotcheck.read_grades(a.csv)
    rep = spotcheck.compare(human, jr["items"])
    print(report.agreement_block(rep))
    print(json.dumps(rep, indent=1))
    return 0


def cmd_graph(a, conn) -> int:
    truths, digest, problems = schema.load_graph_truth(a.graph)
    if problems or not truths:
        raise SystemExit("graph truth problems:\n" + "\n".join(problems) if problems else f"{a.graph} has no repos")
    micro, items = graph_eval.run_graph(conn, truths)
    run_id = store.save_run(conn, "graph", a.label, digest, {"repos": [t.repo for t in truths]}, micro, items)
    print(f"graph run {run_id} saved\n" + report.graph_block(micro, items))
    return 0


def cmd_failures(a, conn) -> int:
    out = {}
    if a.retrieval:
        r = store.load_run(conn, a.retrieval)
        v = a.variant
        out["retrieval"] = fail_mod.retrieval_failures(r["items"][v])
    if a.answers:
        ar = store.load_run(conn, a.answers)
        verdicts = store.load_run(conn, a.judge)["items"] if a.judge else []
        ok = {}
        if a.retrieval:
            ok = {i["id"]: i["file_in_top_k"] for i in store.load_run(conn, a.retrieval)["items"][a.variant]}
        out["answers"] = fail_mod.answer_failures(ar["items"], verdicts, ok)
    if a.graph_run:
        out["graph"] = fail_mod.graph_failures(store.load_run(conn, a.graph_run)["items"])
    for k, fl in out.items():
        print(f"== {k}: {len(fl)} failures {fail_mod.tally(fl)}")
        for f in fl:
            print("  ", json.dumps(f)[:300])
    return 0


def cmd_report(a, conn) -> int:
    parts = []
    if a.retrieval:
        r = store.load_run(conn, a.retrieval)
        base = store.load_run(conn, a.compare)["summary"] if a.compare else None
        parts.append(f"### Retrieval run {r['id']} ({r['label']}, commit {r['git_sha']}, dataset {r['dataset_hash'][:10]})\n\n"
                     + report.retrieval_table(r["summary"], base))
    if a.answers:
        ar = store.load_run(conn, a.answers)
        j = store.load_run(conn, a.judge)["summary"] if a.judge else None
        parts.append(f"### Answers run {ar['id']} ({ar['label']}, model {ar['config'].get('model')})\n\n" + report.answers_block(ar["summary"], j))
    if a.graph_run:
        g = store.load_run(conn, a.graph_run)
        parts.append(f"### Graph run {g['id']} ({g['label']})\n\n" + report.graph_block(g["summary"], g["items"]))
    print("\n".join(parts))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", default=str(Q_DEFAULT))
    ap.add_argument("--graph", default=str(G_DEFAULT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    p = sub.add_parser("retrieval"); p.add_argument("--label", default=""); p.add_argument("--variants", default="all")
    p.add_argument("--embed-missing", action="store_true"); p.add_argument("--allow-incomplete", action="store_true")
    p = sub.add_parser("answers"); p.add_argument("--label", default=""); p.add_argument("--only"); p.add_argument("--rerank", action="store_true")
    p.add_argument("--allow-incomplete", action="store_true")
    p = sub.add_parser("judge"); p.add_argument("--answers", type=int); p.add_argument("--label", default="")
    p.add_argument("--estimate", action="store_true"); p.add_argument("--yes", action="store_true")
    p = sub.add_parser("spotcheck"); p.add_argument("--answers", type=int); p.add_argument("--n", type=int, default=15)
    p.add_argument("--seed", type=int, default=20261020); p.add_argument("--out", default=str(ROOT / "eval" / "spotcheck.csv"))
    p = sub.add_parser("agreement"); p.add_argument("--judge", type=int); p.add_argument("--csv", default=str(ROOT / "eval" / "spotcheck.csv"))
    p = sub.add_parser("graph-eval"); p.add_argument("--label", default="")
    p = sub.add_parser("failures"); p.add_argument("--retrieval", type=int); p.add_argument("--variant", default="ast/hybrid")
    p.add_argument("--answers", type=int); p.add_argument("--judge", type=int); p.add_argument("--graph-run", type=int)
    p = sub.add_parser("report"); p.add_argument("--retrieval", type=int); p.add_argument("--compare", type=int)
    p.add_argument("--answers", type=int); p.add_argument("--judge", type=int); p.add_argument("--graph-run", type=int)
    a = ap.parse_args()
    conn = db.connect()
    fn = {"validate": cmd_validate, "retrieval": cmd_retrieval, "answers": cmd_answers, "judge": cmd_judge,
          "spotcheck": cmd_spotcheck, "agreement": cmd_agreement, "graph-eval": cmd_graph, "failures": cmd_failures,
          "report": cmd_report}[a.cmd]
    return fn(a, conn)


if __name__ == "__main__":
    sys.exit(main())
