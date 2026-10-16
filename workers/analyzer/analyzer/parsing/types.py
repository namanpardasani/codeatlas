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
class ParseResult:
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[RawImport] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)  # exported names ("default" included)
    status: str = "ok"  # ok | partial (syntax errors) | failed | skipped
    error: str | None = None
