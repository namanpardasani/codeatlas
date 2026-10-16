"""tsconfig.json / jsconfig.json are JSON *with comments and trailing commas* (JSONC)."""
import json
import re

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def strip_jsonc(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        else:
            out.append(c)
        i += 1
    return _TRAILING_COMMA.sub(r"\1", "".join(out))


def parse_jsonc(text: str):
    """Return parsed data, or None if the text is not valid even after cleanup."""
    try:
        return json.loads(strip_jsonc(text.lstrip("﻿")))
    except (ValueError, RecursionError):
        return None
