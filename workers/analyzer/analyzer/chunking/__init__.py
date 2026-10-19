"""Chunking entry point. `chunk_file` picks the right chunker for a file and a strategy ('ast' | 'fixed')."""
import posixpath

from .. import config
from ..parsing.types import Symbol
from .ast_chunker import chunk_ast
from .fixed import chunk_fixed
from .sections import chunk_generic, chunk_markdown
from .types import Chunk

PARSED_LANGS = {"typescript", "javascript", "python"}
CODE_LANGS = PARSED_LANGS | {"go", "java", "rust", "ruby", "c", "cpp", "csharp"}
DOC_LANGS = {"markdown", "yaml", "toml", "sql", "shell", "html", "css"}
SMALL_ONLY = {"json": 50 * 1024}
TEXT_EXTS = {".txt", ".rst", ".ini", ".cfg"}


def is_indexable(path: str, language: str | None, size: int) -> bool:
    if language in CODE_LANGS:
        return True
    if language in SMALL_ONLY:
        return size <= SMALL_ONLY[language]
    if language in DOC_LANGS or posixpath.splitext(path)[1].lower() in TEXT_EXTS:
        return size <= config.MAX_DOC_FILE_BYTES
    return False


def chunk_file(path: str, language: str | None, text: str, symbols: list[Symbol], strategy: str = "ast") -> list[Chunk]:
    if strategy == "fixed":
        return chunk_fixed(path, language, text)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if language == "markdown" or path.lower().endswith((".md", ".markdown", ".mdx", ".rst")):
        return chunk_markdown(path, language, lines)
    if language in PARSED_LANGS:
        return chunk_ast(path, language, text, symbols)
    return chunk_generic(path, language, lines)


__all__ = ["Chunk", "chunk_file", "is_indexable"]
