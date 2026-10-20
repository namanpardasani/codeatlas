"""Markdown rendering. Every number printed here comes from a stored run; nothing is typed in by hand."""
from .metrics import mean

COLS = ["recall@1", "recall@3", "recall@5", "recall@10", "mrr"]


def pct(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def retrieval_table(summary: dict, baseline: dict | None = None) -> str:
    head = "| variant | n | " + " | ".join(COLS) + " | hit@5 | MRR 95% CI |\n|---|---|" + "---|" * (len(COLS) + 2) + "\n"
    rows = []
    for name, s in summary.items():
        cells = []
        for c in COLS:
            cell = pct(s[c])
            if baseline and name in baseline:
                d = s[c] - baseline[name][c]
                cell += f" ({d:+.3f})"
            cells.append(cell)
        lo, hi = s["mrr_ci95"]
        rows.append(f"| {name} | {s['n']} | " + " | ".join(cells) + f" | {pct(s['hit@5'])} | {lo:.2f}-{hi:.2f} |")
    return head + "\n".join(rows) + "\n"


def answers_block(a: dict, j: dict | None) -> str:
    lines = [f"- questions: {a['n']} ({a['answered']} answered, {a['errors']} generation errors)",
             f"- correct refusal rate (unanswerable questions refused): {pct(a['correct_refusal_rate'])} (n={a['n_unanswerable']})",
             f"- false refusal rate (answerable questions refused): {pct(a['false_refusal_rate'])} (n={a['n_answerable']})",
             f"- citation file precision / recall (model-written citations vs ground-truth files): {pct(a['citation_file_precision'])} / {pct(a['citation_file_recall'])}",
             f"- answers where the verifier had to remove an unsupported sentence: {pct(a['verifier_removed_sentences_rate'])}"]
    if j:
        lines += [f"- judge ({j['rubric']}): mean correctness {pct(j['mean_correctness'])}, groundedness {pct(j['mean_groundedness'])}, "
                  f"citation validity {pct(j['mean_citation_validity'])} (scale 0-2)",
                  f"- full marks: correctness {pct(j['correctness_full_marks'])}, groundedness {pct(j['groundedness_full_marks'])}, citation {pct(j['citation_validity_full_marks'])}",
                  f"- hallucination rate (any unsupported claim): {pct(j['hallucination_rate_any'])}; serious: {pct(j['hallucination_rate_serious'])} "
                  f"(over {j['n_answers_judged']} answers); judge parse failures: {j['parse_failed']}"]
    return "\n".join(lines) + "\n"


def graph_block(micro: dict, items: list[dict]) -> str:
    rows = "\n".join(f"| {i['repo']} | {i.get('files', '')} | {i.get('truth', '')} | {i.get('predicted', '')} | {pct(i.get('precision'))} | {pct(i.get('recall'))} | {pct(i.get('f1'))} |"
                     for i in items if "precision" in i)
    return (f"| repo | files | true edges | predicted | precision | recall | F1 |\n|---|---|---|---|---|---|---|\n{rows}\n"
            f"| **all (micro)** | | {micro['truth']} | {micro['predicted']} | {pct(micro['precision'])} | {pct(micro['recall'])} | {pct(micro['f1'])} |\n")


def agreement_block(rep: dict) -> str:
    lines = [f"Human graded {rep['n_graded_by_human']} answers; {rep['n_compared']} compared with the judge.\n",
             "| dimension | exact agreement | within 1 | Cohen's kappa | judge mean | human mean | judge - human |", "|---|---|---|---|---|---|---|"]
    for d in ("correctness", "groundedness", "citation_validity"):
        r = rep[d]
        lines.append(f"| {d} | {pct(r['exact'])} | {pct(r['within_one'])} | {pct(r['kappa'])} | {pct(r['judge_mean'])} | {pct(r['human_mean'])} | {pct(r['bias_judge_minus_human'])} |")
    return "\n".join(lines) + "\n"
