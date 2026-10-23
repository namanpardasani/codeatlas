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
    # Fingerprint of the symbol's code tokens (identifiers and literals kept, whitespace/comments/docstrings dropped):
    # equal hashes = same code, so a moved function is recognised as unchanged and a comment-only edit as cosmetic.
    body_hash: str = ""
    bases: list[str] = field(default_factory=list)   # classes: base classes as written ("Base", "mod.Base")


@dataclass
class RawImport:
    """An import as written in source. NOT resolved to a file (that is Day 3)."""
    specifier: str  # "./a", "react", "os.path", "x" (for `from ..x import y`)
    kind: str  # import | require | dynamic | reexport | from
    line: int
    names: list[str] = field(default_factory=list)  # "default", "*", or imported names
    level: int = 0  # Python relative-import dots: `from ..x` -> 2
    is_type_only: bool = False
    # Local names this import creates and what each one refers to in the target module:
    #   (local, imported) where imported is a name, "default", or "*" (the module object itself).
    #   from a import b as c -> ("c", "b") ; import a.b -> ("a.b", "*") ; import x from 'm' -> ("x", "default")
    bindings: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class CallSite:
    """One call as written. Resolution to a symbol happens later (analyzer/blast/callgraph.py)."""
    callee: str               # called name: `f` in f(), obj.f(), new f(), <f />; "" when dynamic
    qualifier: str | None     # what comes before the dot: "obj", "self", "this", "super", "a.b"; "<expr>" if not a name
    line: int
    kind: str = "call"        # call | new | jsx | dynamic (obj[k](), getattr(x, n)(), f()())


@dataclass
class VarType:
    """A cheap type hint: variable `name` holds an instance of `type_name` (x = Foo(), const s: Svc, def f(s: Svc)).
    `name` may be "self.x" / "this.x" for attributes. Used only to upgrade a method call from weak to probable."""
    name: str
    type_name: str            # as written: "Foo" or "mod.Foo"
    line: int


@dataclass
class TestCase:
    """A JS/TS test or suite written as a call: it("name", fn), test(...), describe(...). Python tests are symbols
    (test_* functions / methods) and do not need this."""
    name: str
    kind: str          # test | suite
    start_line: int
    end_line: int


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
    # JS/TS exported name -> local name when they differ: `export { a as b }` -> ("b", "a"); `export default foo` -> ("default", "foo")
    export_aliases: list[tuple[str, str]] = field(default_factory=list)
    status: str = "ok"  # ok | partial (syntax errors) | failed | skipped
    error: str | None = None
    metrics: FileMetrics | None = None
    # Normalized token stream for duplicate detection: token_hashes[i] is the crc32 of the leaf's
    # node type (names/literals collapse to "identifier"/"number"/...), token_lines[i] its line.
    token_hashes: list[int] = field(default_factory=list)
    token_lines: list[int] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    var_types: list[VarType] = field(default_factory=list)
    tests: list[TestCase] = field(default_factory=list)
    # fingerprint of module-level code (everything outside top-level symbols, imports included; comments excluded)
    module_hash: str = ""
    module_code_hash: str = ""   # the same without import statements: tells "only imports changed" from real code
