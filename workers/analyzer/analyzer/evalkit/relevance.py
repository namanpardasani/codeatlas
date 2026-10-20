"""Turning "the correct file(s)/symbol(s)" into something every chunking strategy can be scored against.

Fixed-size windows and AST chunks have different boundaries, so relevance is defined on LINES, not chunk ids:
a hit is relevant to a target when it is in the right file and its line range overlaps the target. A file target
spans the whole file; a symbol target spans the symbol's lines (from the parser's symbol table)."""
from dataclasses import dataclass

from .schema import Question

WHOLE_FILE = 10**9


@dataclass
class Target:
    label: str
    spans: list[tuple[str, int, int]]      # (path, start_line, end_line)


def resolve_targets(conn, repo_id: int, q: Question) -> tuple[list[Target], list[str]]:
    """Returns (targets, problems). Problems name files/symbols that do not exist in the analysed repo."""
    problems: list[str] = []
    known = {r[0] for r in conn.execute("SELECT path FROM files WHERE repo_id = %s", (repo_id,))}
    for f in q.files:
        if f not in known:
            problems.append(f"{q.id}: file {f!r} is not in {q.repo}")
    if not q.symbols:
        return [Target(f, [(f, 1, WHOLE_FILE)]) for f in q.files if f in known], problems
    targets: list[Target] = []
    for sym in q.symbols:
        *parents, name = sym.split(".")
        rows = conn.execute(
            """SELECT f.path, s.start_line, s.end_line FROM symbols s JOIN files f ON f.id = s.file_id
               WHERE s.repo_id = %s AND s.name = %s AND (%s::text IS NULL OR s.parent_name = %s)
                 AND (cardinality(%s::text[]) = 0 OR f.path = ANY(%s::text[]))
               ORDER BY f.path, s.start_line""",
            (repo_id, name, parents[-1] if parents else None, parents[-1] if parents else None, q.files, q.files),
        ).fetchall()
        if not rows:
            problems.append(f"{q.id}: symbol {sym!r} not found" + (f" in {q.files}" if q.files else ""))
            continue
        targets.append(Target(sym, [(r[0], r[1], r[2]) for r in rows]))
    return targets, problems


def covered_by(path: str, start: int, end: int, targets: list[Target]) -> frozenset[int]:
    return frozenset(
        i for i, t in enumerate(targets)
        if any(p == path and start <= e and end >= s for p, s, e in t.spans)
    )
