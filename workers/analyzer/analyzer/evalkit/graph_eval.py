"""Dependency-edge evaluation against a hand-verified ground truth on small repos.

The author lists a closed set of FILES and every true import edge between them. Predicted edges are what the
analyser stored (`dependencies`) restricted to the same set, so precision and recall are over a known universe."""
from . import metrics
from .schema import GraphTruth


def predicted_edges(conn, repo_id: int, files: list[str]) -> set[tuple[str, str]]:
    rows = conn.execute(
        """SELECT a.path, b.path FROM dependencies d JOIN files a ON a.id = d.from_file_id JOIN files b ON b.id = d.to_file_id
           WHERE d.repo_id = %s AND a.path = ANY(%s) AND b.path = ANY(%s)""", (repo_id, files, files)).fetchall()
    return {(a, b) for a, b in rows}


def diagnose_missing(conn, repo_id: int, src: str, dst: str) -> dict:
    """Why might src -> dst be missing? Show how the analyser classified src's imports that look related to dst."""
    stem = dst.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    rows = conn.execute(
        """SELECT i.specifier, i.resolution, i.reason FROM imports_raw i JOIN files f ON f.id = i.file_id
           WHERE i.repo_id = %s AND f.path = %s AND i.specifier ILIKE %s""", (repo_id, src, f"%{stem}%")).fetchall()
    if not rows:
        return {"cause": "no import statement mentioning the target was extracted (parser miss, or dynamic/unusual import)"}
    return {"cause": "import-resolution", "imports": [{"specifier": r[0], "resolution": r[1], "reason": r[2]} for r in rows]}


def run_graph(conn, truths: list[GraphTruth]) -> tuple[dict, list[dict]]:
    items = []
    for t in truths:
        r = conn.execute("SELECT id, status FROM repos WHERE full_name = %s", (t.repo,)).fetchone()
        if not r or r[1] != "ready":
            items.append({"repo": t.repo, "error": "repo not analysed"})
            continue
        res = metrics.edge_prf(predicted_edges(conn, r[0], t.files), t.edges)
        res["false_negative_diagnosis"] = {f"{a} -> {b}": diagnose_missing(conn, r[0], a, b) for a, b in res["false_negatives"]}
        items.append({"repo": t.repo, "files": len(t.files), **res})
    ok = [i for i in items if "precision" in i]
    tp = sum(i["tp"] for i in ok)
    pred = sum(i["predicted"] for i in ok)
    truth = sum(i["truth"] for i in ok)
    prec = tp / pred if pred else None
    rec = tp / truth if truth else None
    micro = {"precision": prec, "recall": rec, "f1": (2 * prec * rec / (prec + rec)) if prec and rec else None,
             "tp": tp, "predicted": pred, "truth": truth, "repos": len(ok)}
    return micro, items
