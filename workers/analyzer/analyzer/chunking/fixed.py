"""BASELINE chunker: plain fixed-size windows with overlap. No syntax awareness (used for the Day 9 comparison)."""
from .. import config
from .types import Chunk, make_header


def chunk_fixed(path: str, language: str | None, text: str) -> list[Chunk]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    size, overlap = config.FIXED_CHUNK_CHARS, config.FIXED_OVERLAP_CHARS
    out: list[Chunk] = []
    i = 0
    while i < len(lines):
        j, total = i, 0
        while j < len(lines) and (total + len(lines[j]) + 1 <= size or j == i):
            total += len(lines[j]) + 1
            j += 1
        body = "\n".join(lines[i:j])
        if body.strip():
            out.append(Chunk(path, language, "window", None, None, i + 1, j, body, make_header(path, "window", None), "fixed"))
        if j >= len(lines):
            break
        back, k = 0, j
        while k - 1 > i and back + len(lines[k - 1]) + 1 <= overlap:  # step back ~overlap chars
            k -= 1
            back += len(lines[k]) + 1
        i = max(k, i + 1)
    return out
