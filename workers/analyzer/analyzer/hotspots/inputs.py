"""Assemble HotspotInputs for every analysed source file from the results of the earlier stages."""
from ..duplication import DupResult
from ..gitstats import GitStats
from ..graph.metrics import GraphAnalysis
from ..inventory import FileRecord
from ..parsing.aggregate import file_aggregates
from ..parsing.types import ParseResult
from .types import HotspotInputs


def build_inputs(records: list[FileRecord], results: dict[str, ParseResult], analysis: GraphAnalysis,
                 git: GitStats, dups: DupResult, tests: dict[str, str | None]) -> list[HotspotInputs]:
    history = git.commits_seen > 0
    out: list[HotspotInputs] = []
    for rec in records:
        res = results.get(rec.path)
        if res is None:
            continue  # not a source file we parse
        agg, m = file_aggregates(res), res.metrics
        fg = git.files.get(rec.path)
        days = None
        if history and fg and fg.last_modified and git.head_time:
            days = max(0, (git.head_time - fg.last_modified).days)
        cyc = analysis.cycle_of.get(rec.path)
        lines = m.lines if m else rec.lines
        fan_in, fan_out = analysis.fan.get(rec.path, (0, 0))
        test_file = tests.get(rec.path)
        out.append(HotspotInputs(
            path=rec.path, is_test=rec.is_test, lines=lines,
            code_lines=m.code_lines if m else 0, comment_ratio=m.comment_ratio if m else 0.0,
            **agg,
            churn=fg.commits_window if fg else 0, commits_total=fg.commits_total if fg else 0, authors=fg.authors if fg else 0, days_since_modified=days,
            in_cycle=cyc is not None, cycle_size=len(analysis.cycles[cyc]) if cyc is not None else 0,
            fan_in=fan_in, fan_out=fan_out, pagerank=analysis.pagerank.get(rec.path, 0.0),
            has_test=test_file is not None, test_file=test_file,
            dup_ratio=min(1.0, dups.duplicated_lines.get(rec.path, 0) / max(lines, 1)),
        ))
    return out
