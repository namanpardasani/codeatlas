"""What changed between the previous analysis and the checkout now? Pure logic, no I/O.

Files are identified by PATH and compared by CONTENT HASH:
  same path, same hash        -> unchanged   (parse results, chunks, vectors, contents are reused)
  same path, different hash   -> modified
  path only in the new tree   -> added
  path only in the old tree   -> deleted
  old path gone + new path with the SAME hash -> renamed (the database row keeps its identity, so its parse results
                                                  and everything attached to it survive the move)

Not detected: a file that was renamed AND edited (content differs) is reported as deleted + added; chasing it would
need a similarity measure and the result (a re-parse) is the same.
"""
from dataclasses import dataclass, field


@dataclass
class Diff:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)   # (old path, new path)
    unchanged: list[str] = field(default_factory=list)

    @property
    def reparse(self) -> list[str]:
        """Files whose CONTENT is new: they must be parsed again."""
        return sorted(self.added + self.modified)

    @property
    def rechunk(self) -> list[str]:
        """Files that need new chunks: new content, or a new path (the path is part of every chunk header)."""
        return sorted(self.added + self.modified + [new for _, new in self.renamed])

    @property
    def changed_count(self) -> int:
        return len(self.added) + len(self.modified) + len(self.renamed)

    def summary(self) -> dict[str, int]:
        return {"added": len(self.added), "modified": len(self.modified), "deleted": len(self.deleted),
                "renamed": len(self.renamed), "unchanged": len(self.unchanged)}


MAX_PAIRING_GROUP = 300


def _similarity(old: str, new: str) -> tuple[bool, int, int]:
    """How plausible is old -> new as a move? Same file name beats everything, then shared trailing folders, then
    shared leading folders. Used only to pair files with IDENTICAL content (e.g. many empty __init__.py)."""
    o, n = old.split("/"), new.split("/")
    same_name = o[-1] == n[-1]
    tail = 0
    for a, b in zip(reversed(o), reversed(n)):
        if a != b:
            break
        tail += 1
    head = 0
    for a, b in zip(o, n):
        if a != b:
            break
        head += 1
    return (same_name, tail, head)


def classify(old: dict[str, str], new: dict[str, str]) -> Diff:
    """old/new: path -> content hash."""
    d = Diff()
    for path in sorted(old.keys() & new.keys()):
        (d.unchanged if old[path] == new[path] else d.modified).append(path)
    gone = sorted(old.keys() - new.keys())
    fresh = sorted(new.keys() - old.keys())

    by_hash_old: dict[str, list[str]] = {}
    for p in gone:
        by_hash_old.setdefault(old[p], []).append(p)
    by_hash_new: dict[str, list[str]] = {}
    for p in fresh:
        by_hash_new.setdefault(new[p], []).append(p)

    paired_old: set[str] = set()
    paired_new: set[str] = set()
    for h, olds in by_hash_old.items():
        news = by_hash_new.get(h)
        if not news:
            continue
        if len(olds) > MAX_PAIRING_GROUP or len(news) > MAX_PAIRING_GROUP:
            pairs = list(zip(olds, news))                       # absurdly many identical files: pair in order
        else:
            # best-first greedy assignment; ties break on the paths themselves, so the result is deterministic
            candidates = sorted(((o, n, *_similarity(o, n)) for o in olds for n in news),
                                key=lambda t: (-int(t[2]), -t[3], -t[4], t[0], t[1]))
            pairs, used_o, used_n = [], set(), set()
            for o, n, *_ in candidates:
                if o not in used_o and n not in used_n:
                    pairs.append((o, n))
                    used_o.add(o)
                    used_n.add(n)
        for o, n in pairs:
            d.renamed.append((o, n))
            paired_old.add(o)
            paired_new.add(n)

    d.deleted = [p for p in gone if p not in paired_old]
    d.added = [p for p in fresh if p not in paired_new]
    d.renamed.sort()
    return d
