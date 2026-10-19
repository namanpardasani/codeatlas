import hashlib
from dataclasses import dataclass


@dataclass
class Chunk:
    path: str
    language: str | None
    kind: str                 # function | method | class | interface | type | enum | module | group | section | window
    symbol: str | None        # qualified name ("Request.prepare_body"), section title, or None
    parent: str | None        # enclosing class
    start_line: int           # 1-based, inclusive
    end_line: int
    content: str
    header: str               # short context line: path + enclosing class + symbol
    strategy: str = "ast"     # ast | fixed

    @property
    def embed_text(self) -> str:
        """What gets embedded and keyword-indexed: the header gives the model/FTS the path and context."""
        return f"{self.header}\n{self.content}"

    @property
    def embed_hash(self) -> str:
        return hashlib.sha256(self.embed_text.encode("utf8", errors="replace")).hexdigest()


def make_header(path: str, kind: str, symbol: str | None, part: tuple[int, int] | None = None) -> str:
    if kind == "window":
        return path
    what = {"module": "module-level code", "section": symbol or "section"}.get(kind)
    label = what if what else f"{symbol} ({kind})" if symbol else kind
    suffix = f" [part {part[0]}/{part[1]}]" if part and part[1] > 1 else ""
    return f"{path} :: {label}{suffix}"
