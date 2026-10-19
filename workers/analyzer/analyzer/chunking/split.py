"""Line-based splitting helpers shared by the chunkers."""
from .. import config


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def split_lines(lines: list[str], start: int, end: int, max_chars: int | None = None,
                overlap: int | None = None) -> list[tuple[int, int]]:
    """Split lines[start-1:end] (1-based inclusive) into windows of <= max_chars at logical breaks.

    A break is preferred at a blank line (the one before the shallowest-indented following line wins:
    that is the boundary between top-level blocks), searched in the last 40% of the window; otherwise
    the window is cut at the line limit. Consecutive windows overlap by `overlap` lines.
    """
    max_chars = config.CHUNK_MAX_CHARS if max_chars is None else max_chars
    overlap = config.CHUNK_OVERLAP_LINES if overlap is None else overlap
    parts: list[tuple[int, int]] = []
    s = start
    while s <= end:
        size, e = 0, s
        while e <= end and (size + len(lines[e - 1]) + 1 <= max_chars or e == s):
            size += len(lines[e - 1]) + 1
            e += 1
        e -= 1  # last line that fits
        if e < end:  # not the final window: look for a logical break
            lo = s + int((e - s) * 0.6)
            best, best_key = None, None
            for i in range(lo, e):
                if not lines[i - 1].strip():
                    nxt = next((j for j in range(i + 1, e + 1) if lines[j - 1].strip()), None)
                    if nxt is None:
                        continue
                    key = (indent_of(lines[nxt - 1]), -i)  # shallowest next line, then latest break
                    if best_key is None or key < best_key:
                        best, best_key = i, key
            if best is not None:
                e = best
        parts.append((s, e))
        if e >= end:
            break
        s = max(e + 1 - overlap, parts[-1][0] + 1)  # always make progress
    return parts


def paragraph_chunks(lines: list[str], start: int, end: int, max_chars: int | None = None) -> list[tuple[int, int]]:
    """Group blank-line separated paragraphs into windows of <= max_chars (long paragraphs are line-split)."""
    max_chars = config.CHUNK_MAX_CHARS if max_chars is None else max_chars
    paras: list[tuple[int, int]] = []
    s = None
    for i in range(start, end + 1):
        if lines[i - 1].strip():
            s = i if s is None else s
        elif s is not None:
            paras.append((s, i - 1))
            s = None
    if s is not None:
        paras.append((s, end))
    out: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = None
    for a, b in paras:
        if sum(len(x) + 1 for x in lines[a - 1:b]) > max_chars:
            if cur:
                out.append(cur)
                cur = None
            out.extend(split_lines(lines, a, b, max_chars, overlap=0))
            continue
        if cur and sum(len(x) + 1 for x in lines[cur[0] - 1:b]) <= max_chars:
            cur = (cur[0], b)
        else:
            if cur:
                out.append(cur)
            cur = (a, b)
    if cur:
        out.append(cur)
    return out
