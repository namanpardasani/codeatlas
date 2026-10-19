import glob
import re
from pathlib import Path

import pytest

from analyzer import config
from analyzer.chunking import chunk_file, is_indexable
from analyzer.chunking.fixed import chunk_fixed
from analyzer.chunking.sections import markdown_sections
from analyzer.parsing import parse_source


def chunks_of(path, text, strategy="ast"):
    lang = {"py": "python", "ts": "typescript", "js": "javascript", "md": "markdown"}.get(path.rsplit(".", 1)[-1])
    syms = parse_source(path, text.encode()).symbols if lang in ("python", "typescript", "javascript") else []
    return chunk_file(path, lang, text, syms, strategy)


PY = '''"""Module docs."""
import os
import sys

LIMIT = 10


@decorator
def helper(a, b):
    """Add."""
    return a + b


def other():
    return 1


class Service:
    """A service."""
    name = "svc"

    def start(self):
        return 1

    def stop(self):
        return 2
'''

TS = '''import { a } from "./a";

/**
 * Adds numbers.
 */
export function add(x: number, y: number): number {
  return x + y;
}

export const handler = async (req) => {
  return req;
};

class K {
  run() { return 1; }
}
'''


@pytest.fixture
def no_merge(monkeypatch):
    monkeypatch.setattr(config, "CHUNK_MIN_CHARS", 1)
    monkeypatch.setattr(config, "CHUNK_TINY_CHARS", 1)


def find(chunks, symbol):
    return next(c for c in chunks if c.symbol == symbol)


def test_one_chunk_per_small_symbol_with_context_header(no_merge):
    cs = chunks_of("src/app.py", PY, "ast")
    helper = next(c for c in cs if c.symbol and "helper" in c.symbol)
    assert "@decorator" in helper.content and helper.content.lstrip().startswith("@decorator")  # decorator attached
    assert helper.kind == "function" and helper.symbol == "helper"
    assert helper.header.startswith("src/app.py ::")
    assert cs[0].kind == "module" and "import os" in cs[0].content            # imports -> module-level chunk


def test_methods_are_their_own_chunks_with_class_context_when_the_class_is_big(monkeypatch, no_merge):
    monkeypatch.setattr(config, "CHUNK_MAX_CHARS", 100)
    cs = chunks_of("src/app.py", PY, "ast")
    start = find(cs, "Service.start")
    assert (start.kind, start.parent) == ("method", "Service")
    assert "Service.start (method)" in start.header
    assert any(c.symbol == "Service" and c.kind == "class" and "A service" in c.content for c in cs)  # class header chunk


def test_jsdoc_is_attached_to_its_function(no_merge):
    cs = chunks_of("src/a.ts", TS)
    add = next(c for c in cs if c.symbol and c.symbol.startswith("add"))
    assert "Adds numbers" in add.content and add.start_line == 3


def test_oversized_function_is_split_with_overlap_and_part_labels(monkeypatch, no_merge):
    monkeypatch.setattr(config, "CHUNK_MAX_CHARS", 400)
    body = "\n".join(f"    value_{i} = compute({i}) + other_{i}" + ("\n" if i % 6 == 5 else "") for i in range(40))
    src = f"def big(x):\n{body}\n    return x\n"
    cs = [c for c in chunks_of("big.py", src) if c.symbol == "big"]
    assert len(cs) >= 3
    assert all("[part" in c.header for c in cs) and cs[0].header.endswith(f"[part 1/{len(cs)}]")
    assert all(len(c.content) <= 400 + 80 for c in cs)
    for a, b in zip(cs, cs[1:]):
        assert b.start_line <= a.end_line + 1                    # no gap
        assert b.start_line > a.start_line                       # progress
    assert any(b.start_line <= a.end_line for a, b in zip(cs, cs[1:]))   # at least one overlap


def test_small_adjacent_symbols_are_merged_into_a_group():
    src = "def a():\n    return 1\n\ndef b():\n    return 2\n\ndef c():\n    return 3\n"
    cs = chunks_of("m.py", src)
    assert len(cs) == 1 and cs[0].kind == "group" and cs[0].symbol == "a, b, c"
    assert (cs[0].start_line, cs[0].end_line) == (1, 8)


def test_symbols_with_different_parents_are_not_merged(monkeypatch):
    monkeypatch.setattr(config, "CHUNK_MAX_CHARS", 60)
    monkeypatch.setattr(config, "CHUNK_TINY_CHARS", 1000)  # everything is 'tiny': only the parent rule stops merging
    cs = chunks_of("m.py", "class A:\n    def f(self):\n        return 1\n\n    def g(self):\n        return 2\n\ndef top():\n    return 3\n")
    assert {c.parent for c in cs} >= {None, "A"}


def test_markdown_sections_use_the_heading_path_and_ignore_fenced_headings():
    md = "# Title\nintro\n\n## Install\nrun it\n\n```bash\n# not a heading\nls\n```\n\n## Usage\n### CLI\nargs\n"
    secs = markdown_sections(md.split("\n"))
    assert [t for _, _, t in secs] == ["Title", "Title > Install", "Title > Usage", "Title > Usage > CLI"]
    cs = chunks_of("README.md", md)
    assert {c.symbol for c in cs} >= {"Title > Install", "Title > Usage > CLI"}
    install = find(cs, "Title > Install")
    assert "# not a heading" in install.content           # the fenced line stayed inside its section


def test_unparsed_languages_use_paragraph_sections():
    text = "key: 1\nother: 2\n\nsection:\n  a: 1\n"
    cs = chunk_file("conf.yaml", "yaml", text, [], "ast")
    assert len(cs) == 1 and cs[0].kind == "section"          # small paragraphs merged


def test_fixed_chunker_baseline_size_overlap_and_coverage():
    text = "\n".join(f"line number {i} with some padding text" for i in range(200))
    cs = chunk_fixed("f.txt", None, text)
    assert all(c.kind == "window" and c.strategy == "fixed" for c in cs)
    assert all(len(c.content) <= config.FIXED_CHUNK_CHARS + 60 for c in cs)
    assert cs[0].start_line == 1 and cs[-1].end_line == 200
    for a, b in zip(cs, cs[1:]):
        assert a.start_line < b.start_line <= a.end_line + 1   # moves forward, overlaps or touches
    assert any(b.start_line <= a.end_line for a, b in zip(cs, cs[1:]))
    assert cs == chunk_fixed("f.txt", None, text)               # deterministic


def test_empty_and_blank_files_produce_no_chunks():
    for strategy in ("ast", "fixed"):
        assert chunks_of("e.py", "", strategy) == [] and chunks_of("e.py", "\n\n\n", strategy) == []


def test_is_indexable():
    assert is_indexable("a.py", "python", 10) and is_indexable("README.md", "markdown", 1000)
    assert is_indexable("a.json", "json", 1000) and not is_indexable("big.json", "json", 10**6)
    assert not is_indexable("logo.png", None, 100) and not is_indexable("a.yaml", "yaml", 10**7)


# ---- properties over real code: this project's own sources ---------------------------------------
CORPUS = sorted(glob.glob(str(Path(__file__).parent.parent / "analyzer" / "**" / "*.py"), recursive=True))


@pytest.mark.parametrize("strategy", ["ast", "fixed"])
@pytest.mark.parametrize("file", CORPUS)
def test_every_meaningful_line_is_covered_and_chunks_are_well_formed(file, strategy):
    text = Path(file).read_text()
    cs = chunks_of(file.rsplit("/analyzer/", 1)[-1], text, strategy)
    lines = text.split("\n")
    covered = set()
    for c in cs:
        assert 1 <= c.start_line <= c.end_line <= len(lines)
        assert c.content == "\n".join(lines[c.start_line - 1:c.end_line])          # content is exactly that range
        assert len(c.content) <= config.CHUNK_MAX_CHARS * 1.3 + 200, (c.header, len(c.content))
        covered.update(range(c.start_line, c.end_line + 1))
    missing = [i for i, ln in enumerate(lines, 1) if re.search(r"\w", ln) and i not in covered]
    assert not missing, f"uncovered lines in {file}: {missing[:5]}"
    assert cs == chunks_of(file.rsplit("/analyzer/", 1)[-1], text, strategy)       # deterministic


def test_ast_strategy_never_cuts_a_small_function_in_half():
    """The point of AST chunking: every function that fits is inside exactly one chunk."""
    for file in CORPUS:
        text = Path(file).read_text()
        r = parse_source(file, text.encode())
        cs = chunks_of(file.rsplit("/analyzer/", 1)[-1], text)
        for s in r.symbols:
            if s.kind in ("function", "method") and len("\n".join(text.split("\n")[s.start_line - 1:s.end_line])) <= config.CHUNK_MAX_CHARS:
                holders = [c for c in cs if c.start_line <= s.start_line and c.end_line >= s.end_line]
                assert holders, f"{file}:{s.name} is split across chunks"
