from .types import ParseResult

FUNCTION_KINDS = ("function", "method")


def file_aggregates(result: ParseResult) -> dict:
    """Per-file roll-up of the per-function metrics."""
    fns = [s for s in result.symbols if s.kind in FUNCTION_KINDS and s.complexity is not None]
    return {
        "function_count": len(fns),
        "total_complexity": sum(s.complexity for s in fns),
        "max_complexity": max((s.complexity for s in fns), default=0),
        "max_nesting": max((s.max_nesting for s in fns), default=0),
        "longest_function": max((s.end_line - s.start_line + 1 for s in fns), default=0),
    }
