"""BlastReport -> JSON for the API, the UI, MCP and the PR comment. Every list is capped so a huge change cannot
produce a huge response (the MCP output limit and the PR comment size both depend on it)."""
from .engine import BlastReport

MAX_FILES = 60
MAX_SYMBOLS = 60
MAX_TESTS = 150
MAX_CHANGED = 150
MAX_PATH_STEPS = 6


def _steps(path) -> list[dict]:
    steps = path[-MAX_PATH_STEPS:]
    return [{"node": list(s.node), "edge": s.edge, "reason": s.reason} for s in steps]


def to_json(rep: BlastReport, *, file_ids: dict[str, int] | None = None, input_kind: str = "", input_ref: str = "") -> dict:
    ids = file_ids or {}
    cs = rep.changes
    out: dict = {
        "input": {"kind": input_kind, "ref": input_ref[:300]},
        "base_sha": rep.change.base, "head_sha": rep.change.head,
        "timings_ms": rep.timings_ms,
        "change": {
            "stats": cs.stats(),
            "files": [{"path": f.path, "old_path": f.old_path, "status": f.status, "category": f.category,
                       "added": f.added_lines, "deleted": f.deleted_lines, "module_changed": f.module_changed,
                       "imports_only": f.imports_only, "error": f.error, "file_id": ids.get(f.old_path or f.path),
                       "symbols": [{"change": s.change, "kind": s.kind, "name": s.name, "note": s.note}
                                   for s in f.symbols if s.semantic][:40]}
                      for f in cs.files][:MAX_CHANGED],
        },
    }
    if rep.impact is None:                    # first commit of a repo: nothing existed to break
        out.update(impact=None, tests=None, risk=None, reviewers=[])
        return out
    imp = rep.impact
    name = rep.base.calls.name if rep.base else (lambda r: "")
    from .callgraph import SymRef
    out["impact"] = {
        "params": {"decay": imp.params.decay, "max_depth": imp.params.max_depth, "combine": imp.params.combine},
        "files": [{"path": f.path_str, "file_id": ids.get(f.path_str), "score": round(f.score, 4), "distance": f.distance,
                   "edges": f.edge_types, "reason": f.reason, "why": _steps(f.path)} for f in imp.files[:MAX_FILES]],
        "symbols": [{"path": s.node[1], "name": name(SymRef(s.node[1], s.node[2])), "file_id": ids.get(s.node[1]),
                     "score": round(s.score, 4), "distance": s.distance, "reason": s.reason, "why": _steps(s.path)}
                    for s in imp.symbols[:MAX_SYMBOLS]],
        "seeds": [{"node": list(s.node), "score": s.score, "reason": s.path[0].reason if s.path else ""} for s in imp.seeds][:80],
        "total_files": len(imp.files), "total_symbols": len(imp.symbols),
    }
    t = rep.tests
    out["tests"] = None if t is None else {
        "summary": t.summary(), "total": t.total, "selected_count": len(t.selected), "ratio": round(t.ratio, 4),
        "full_suite": t.full_suite, "full_suite_reasons": t.full_suite_reasons, "framework": t.framework,
        "command": t.command[:2000],
        "selected": [{"file": s.unit.file, "name": s.unit.name, "score": s.score, "reason": s.reason}
                     for s in t.selected[:MAX_TESTS]],
        "new_tests": [{"file": u.file, "name": u.name} for u in t.new_tests[:50]],
    }
    r = rep.risk
    out["risk"] = None if r is None else {
        "score": r.score, "label": r.label, "model": r.model, "top_factors": r.top_factors,
        "factors": [{"feature": k, "contribution": c, "text": w} for k, c, w in r.factors],
        "missing_cochanges": [{"file": m.file, "partner_of": m.partner_of, "confidence": m.confidence,
                               "support": m.support, "text": m.text()} for m in r.missing_cochanges[:10]],
    }
    out["reviewers"] = [{"name": v.name, "commits": v.commits, "files": v.files[:5], "reason": v.reason()} for v in rep.reviewers]
    return out
