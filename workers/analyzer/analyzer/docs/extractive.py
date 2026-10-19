"""Deterministic summaries built only from names, docstrings and the dependency graph: no LLM, nothing invented.
They are the fallback when the LLM budget is exhausted, the model is unavailable or a generated summary fails the guard."""
import re

FIRST_SENTENCE = re.compile(r"(.+?[.!?])(\s|$)", re.S)


def first_sentence(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    m = FIRST_SENTENCE.match(text)
    return (m.group(1) if m else text)[:limit]


def symbol_doc(lines: list[str], start: int, end: int, language: str | None) -> str:
    """The docstring (Python) or the JSDoc block right above the symbol (JS/TS), if there is one."""
    if language == "python":
        head = "\n".join(lines[start - 1:min(end, start + 14)])
        m = re.search(r':\s*\n\s*[rRbBuU]*("""|\'\'\')(.+?)\1', head, re.S)
        return re.sub(r"\s+", " ", m.group(2)).strip() if m else ""
    i = start - 2
    while i >= 0 and not lines[i].strip():
        break
    if i >= 0 and lines[i].strip().endswith("*/"):
        j = i
        while j >= 0 and "/**" not in lines[j]:
            j -= 1
        if j >= 0:
            body = [re.sub(r"^\s*(/\*\*|\*/|\*)\s?", "", ln).strip() for ln in lines[j:i + 1]]
            return " ".join(x for x in body if x and not x.startswith("@"))
    return ""


def symbol_summary(path: str, qualified: str, kind: str, start: int, end: int, params: list[str], doc: str) -> str:
    sig = f"`{qualified}({', '.join(params)})`" if kind in ("function", "method") else f"`{qualified}`"
    base = f"{sig} is a {kind} in `{path}` (lines {start}-{end})."
    d = first_sentence(doc)
    return f"{base} {d}" if d else base


def file_summary(path: str, language: str | None, lines: int, symbols: list[tuple[str, str]], imports_internal: list[str],
                 imported_by: int, module_doc: str = "") -> str:
    parts = [f"`{path}` is a {language or 'text'} file of {lines} lines."]
    d = first_sentence(module_doc)
    if d:
        parts.append(d)
    if symbols:
        names = ", ".join(f"`{n}` ({k})" for n, k in symbols[:8]) + (f" and {len(symbols) - 8} more" if len(symbols) > 8 else "")
        parts.append(f"It defines {names}.")
    if imports_internal:
        parts.append("It imports from " + ", ".join(f"`{p}`" for p in imports_internal[:5]) + (", and others." if len(imports_internal) > 5 else "."))
    if imported_by:
        parts.append(f"{imported_by} other file(s) import it.")
    return " ".join(parts)


def folder_summary(path: str, files: list[tuple[str, str]], subfolders: list[str]) -> str:
    where = f"`{path}/`" if path else "The repository root"
    parts = [f"{where} contains {len(files)} analysed file(s)" + (f" and {len(subfolders)} sub-folder(s)" if subfolders else "") + "."]
    if files:
        parts.append("Files: " + ", ".join(f"`{p}`" for p, _ in files[:6]) + (f", and {len(files) - 6} more." if len(files) > 6 else "."))
    if subfolders:
        parts.append("Sub-folders: " + ", ".join(f"`{p}/`" for p in subfolders[:6]) + (", and more." if len(subfolders) > 6 else "."))
    return " ".join(parts)


def repo_summary(full_name: str, readme_excerpt: str, languages: list[dict], entry_points: list[dict]) -> str:
    parts = [f"`{full_name}`."]
    d = first_sentence(re.sub(r"^#.*$", "", readme_excerpt or "", flags=re.M), 300)
    if d:
        parts.append(f"README: {d}")
    if languages:
        parts.append("Languages: " + ", ".join(f"{l['language']} ({l['files']} files)" for l in languages[:4]) + ".")
    if entry_points:
        parts.append("Entry points: " + ", ".join(f"`{e['path']}`" for e in entry_points[:4]) + ".")
    return " ".join(parts)
