from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str
    kind: str  # function | class | method | interface | type | enum
    start_line: int  # 1-based, inclusive
    end_line: int
    params: list[str] = field(default_factory=list)
    parent: str | None = None  # enclosing class/function name
    is_exported: bool = False
    is_default_export: bool = False
    has_doc: bool = False  # JSDoc / docstring present
    signature: str = ""  # first source line, truncated
    complexity: int | None = None  # cyclomatic complexity (functions/methods only)
    max_nesting: int = 0           # deepest control-flow nesting inside the body
    param_count: int = 0           # parameters (Python self/cls excluded)


@dataclass
class RawImport:
    """An import as written in source. NOT resolved to a file (that is Day 3)."""
    specifier: str  # "./a", "react", "os.path", "x" (for `from ..x import y`)
    kind: str  # import | require | dynamic | reexport | from
    line: int
    names: list[str] = field(default_factory=list)  # "default", "*", or imported names
    level: int = 0  # Python relative-import dots: `from ..x` -> 2
    is_type_only: bool = False


@dataclass
class FileMetrics:
    lines: int = 0
    blank_lines: int = 0
    comment_lines: int = 0   # lines holding only comment text (Python docstrings included)
    code_lines: int = 0      # non-blank lines that are not comment-only
    comment_ratio: float = 0.0  # comment_lines / non-blank lines


@dataclass
class ParseResult:
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[RawImport] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)  # exported names ("default" included)
    status: str = "ok"  # ok | partial (syntax errors) | failed | skipped
    error: str | None = None
    metrics: FileMetrics | None = None
    # Normalized token stream for duplicate detection: token_hashes[i] is the crc32 of the leaf's
    # node type (names/literals collapse to "identifier"/"number"/...), token_lines[i] its line.
    token_hashes: list[int] = field(default_factory=list)
    token_lines: list[int] = field(default_factory=list)
