"""Token-based duplicate-code detection (works across files, ignores renames/whitespace/comments).

Input per file: the normalized token stream from the parser (token type hashes + line numbers).
1. Rolling-hash every window of WINDOW tokens (O(total tokens)).
2. A window hash seen at 2+ non-overlapping places is duplicated (low-variety windows ignored).
3. Consecutive duplicated windows merge into one maximal block per file.
4. Blocks sharing a window hash are connected (union-find) into a group of copies.
5. Blocks shorter than MIN_LINES are dropped.
"""
from collections import defaultdict
from dataclasses import dataclass, field

WINDOW = 50          # min tokens in a duplicate
MIN_LINES = 6        # min lines in a reported block
MIN_DISTINCT = 6     # windows with fewer distinct token kinds are boilerplate/data tables
MAX_TOTAL_TOKENS = 1_500_000
MAX_GROUPS = 200
MAX_LOCATIONS = 20
_MOD = (1 << 61) - 1
_BASE = 1_000_003


@dataclass
class Location:
    path: str
    start_line: int
    end_line: int


@dataclass
class DupGroup:
    lines: int                 # lines of the largest copy
    tokens: int
    locations: list[Location]
    total_locations: int


@dataclass
class DupResult:
    groups: list[DupGroup] = field(default_factory=list)
    duplicated_lines: dict[str, int] = field(default_factory=dict)  # path -> lines inside any duplicate block
    truncated: bool = False    # token budget exceeded: some files were not analysed


def _window_hashes(tokens: list[int], w: int) -> list[int]:
    n = len(tokens)
    if n < w:
        return []
    top = pow(_BASE, w - 1, _MOD)
    h = 0
    for t in tokens[:w]:
        h = (h * _BASE + t) % _MOD
    out = [h]
    for i in range(1, n - w + 1):
        h = ((h - tokens[i - 1] * top) * _BASE + tokens[i + w - 1]) % _MOD
        out.append(h)
    return out


class _DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def find_duplicates(files: dict[str, tuple[list[int], list[int]]], window: int = WINDOW,
                    min_lines: int = MIN_LINES, max_total_tokens: int = MAX_TOTAL_TOKENS) -> DupResult:
    result = DupResult()
    paths = sorted(files)  # deterministic regardless of input order
    hashes: dict[str, list[int]] = {}
    budget = max_total_tokens
    for p in paths:
        toks = files[p][0]
        if len(toks) < window:
            continue
        if len(toks) > budget:
            result.truncated = True
            continue
        budget -= len(toks)
        hashes[p] = _window_hashes(toks, window)

    # 1. where does each window hash occur?
    where: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for p, hs in hashes.items():
        for i, h in enumerate(hs):
            where[h].append((p, i))

    # 2. keep hashes with >= 2 NON-overlapping occurrences and enough token variety
    flagged: dict[str, set[int]] = defaultdict(set)
    dup_hash_positions: dict[int, list[tuple[str, int]]] = {}
    for h, occ in where.items():
        if len(occ) < 2:
            continue
        p0, i0 = occ[0]
        if len(set(files[p0][0][i0:i0 + window])) < MIN_DISTINCT:
            continue
        kept, last_end = [], {}
        for p, i in occ:  # occ is ordered by (path, index): greedy non-overlap per file
            if i >= last_end.get(p, -1):
                kept.append((p, i))
                last_end[p] = i + window
        if len(kept) >= 2:
            dup_hash_positions[h] = kept
            for p, i in kept:
                flagged[p].add(i)

    # 3. merge consecutive flagged windows into blocks (runs)
    runs: list[tuple[str, int, int]] = []          # (path, first window, last window)
    run_of: dict[tuple[str, int], int] = {}
    for p in sorted(flagged):
        idxs = sorted(flagged[p])
        start = prev = idxs[0]
        for i in idxs[1:] + [None]:
            if i is not None and i == prev + 1:
                prev = i
                continue
            rid = len(runs)
            runs.append((p, start, prev))
            for k in range(start, prev + 1):
                run_of[(p, k)] = rid
            if i is not None:
                start = prev = i

    def line_span(run):
        p, s, e = run
        lines = files[p][1]
        return lines[s], lines[e + window - 1]

    # 5. drop short blocks; 4. connect blocks that share a window hash
    keep = [r for r, run in enumerate(runs) if (lambda a, b: b - a + 1)(*line_span(run)) >= min_lines]
    keep_set = set(keep)
    dsu = _DSU(len(runs))
    for positions in dup_hash_positions.values():
        rids = [run_of[pos] for pos in positions if run_of.get(pos) in keep_set]
        for other in rids[1:]:
            dsu.union(rids[0], other)

    comps: dict[int, list[int]] = defaultdict(list)
    for r in keep:
        comps[dsu.find(r)].append(r)

    dup_rows: dict[str, set[int]] = defaultdict(set)
    groups: list[DupGroup] = []
    for rids in comps.values():
        if len(rids) < 2:
            continue
        locs = []
        for r in sorted(rids, key=lambda r: (runs[r][0], runs[r][1])):
            a, b = line_span(runs[r])
            locs.append(Location(runs[r][0], a, b))
            dup_rows[runs[r][0]].update(range(a, b + 1))
        biggest = max(rids, key=lambda r: runs[r][2] - runs[r][1])
        groups.append(DupGroup(
            lines=max(loc.end_line - loc.start_line + 1 for loc in locs),
            tokens=runs[biggest][2] - runs[biggest][1] + window,
            locations=locs[:MAX_LOCATIONS], total_locations=len(locs)))

    groups.sort(key=lambda g: (-(g.lines * g.total_locations), g.locations[0].path, g.locations[0].start_line))
    result.groups = groups[:MAX_GROUPS]
    result.duplicated_lines = {p: len(rows) for p, rows in sorted(dup_rows.items())}
    return result
