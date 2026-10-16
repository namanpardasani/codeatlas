from dataclasses import dataclass, field


@dataclass
class Resolution:
    """Outcome of resolving ONE import statement.

    internal   -> `targets` are repo-relative paths of files in the analysed repo
    external   -> a package outside the repo (npm package, Node builtin, Python stdlib/third-party);
                  kept as a list, never a graph node
    unresolved -> looked internal but no file matched; `reason` says why. We record, never guess.
    """
    status: str  # internal | external | unresolved
    targets: list[str] = field(default_factory=list)
    package: str | None = None
    reason: str | None = None


@dataclass
class ImportItem:
    from_path: str
    idx: int  # position in the file's imports (matches imports_raw.idx)
    specifier: str
    kind: str
    names: list[str]
    level: int = 0


@dataclass
class ImportResolution:
    from_path: str
    idx: int
    kind: str
    resolution: Resolution
