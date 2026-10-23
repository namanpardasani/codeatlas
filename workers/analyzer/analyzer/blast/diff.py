"""Unified diff parsing (git flavour) and patch application.

A diff is untrusted input (uploaded by a user or fetched from a public PR), so parsing is strict and bounded:
size and file-count limits, no path that escapes the repo, malformed hunks rejected with a reason instead of guessed.

Line numbers: in a hunk `@@ -a,b +c,d @@`, old-side lines count from `a` and new-side lines from `c`.
  ' ' context  -> advances both sides
  '-' deleted  -> an OLD line that is gone          (recorded in `deleted`, old numbering)
  '+' added    -> a NEW line that did not exist     (recorded in `added`, new numbering)
A pure insertion has no old line, so `anchors` also records, for every added run, the old line it was inserted
after: a function that grew by one line in the middle was touched even though none of its old lines was deleted.
"""
import posixpath
import re
from dataclasses import dataclass, field

MAX_DIFF_BYTES = 5 * 1024 * 1024
MAX_FILES = 3000

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffError(ValueError):
    pass


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list[str] = field(default_factory=list)       # raw hunk body lines, prefix included


@dataclass
class FileDiff:
    old_path: str | None          # None when the file was added
    new_path: str | None          # None when the file was deleted
    status: str                   # added | deleted | modified | renamed | binary | mode_only
    hunks: list[Hunk] = field(default_factory=list)
    deleted: set[int] = field(default_factory=set)       # old-side line numbers removed
    added: set[int] = field(default_factory=set)         # new-side line numbers added
    anchors: set[int] = field(default_factory=set)       # old-side lines right before an insertion
    similarity: int | None = None                        # rename similarity (git -M), percent

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


def _unquote(p: str) -> str:
    """git quotes unusual paths in C style: "a\\tb". Decode the common escapes; octal bytes as UTF-8."""
    if not (len(p) >= 2 and p[0] == p[-1] == '"'):
        return p
    body = p[1:-1]
    out = bytearray()
    i = 0
    simple = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r", "v": b"\v"}
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in simple:
                out += simple[nxt]
                i += 2
                continue
            if re.match(r"[0-7]{3}", body[i + 1:i + 4]):
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
        out += ch.encode()
        i += 1
    return out.decode("utf-8", errors="replace")


def _clean(p: str | None, prefix: str) -> str | None:
    """Strip the a/ or b/ prefix, reject /dev/null, absolute paths and `..` escapes."""
    if p is None:
        return None
    p = _unquote(p.strip())
    if p == "/dev/null":
        return None
    if p.startswith(prefix):
        p = p[len(prefix):]
    norm = posixpath.normpath(p)
    if norm.startswith("/") or norm == ".." or norm.startswith("../") or "\x00" in norm:
        raise DiffError(f"unsafe path in diff: {p[:100]!r}")
    return norm


def _split_git_header(rest: str) -> tuple[str | None, str | None]:
    """`diff --git a/x b/y` (paths may contain spaces; quoted when they contain odd characters)."""
    if rest.startswith('"'):
        m = re.match(r'^("(?:[^"\\]|\\.)*")\s+(.*)$', rest)
        return (m.group(1), m.group(2)) if m else (None, None)
    # unquoted: a/<p> b/<p>; when old == new the split point is the middle " b/"
    if " b/" in rest:
        half = (len(rest) - 1) // 2
        if rest[:half].startswith("a/") and rest[half + 1:].startswith("b/") and rest[2:half] == rest[half + 3:]:
            return rest[:half], rest[half + 1:]
        i = rest.rfind(" b/")
        return rest[:i], rest[i + 1:]
    parts = rest.split(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (None, None)


def parse_diff(text: str) -> list[FileDiff]:
    if len(text.encode("utf-8", errors="replace")) > MAX_DIFF_BYTES:
        raise DiffError(f"diff is larger than {MAX_DIFF_BYTES // (1024 * 1024)} MB")
    lines = text.split("\n")
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    i = 0

    def finish():
        if cur is None:
            return
        if cur.status == "modified" and not cur.hunks and cur.old_path == cur.new_path:
            cur.status = "mode_only"
        if cur.status == "renamed" and cur.hunks:
            pass                                      # renamed with edits keeps "renamed"; hunks say what changed
        files.append(cur)

    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            finish()
            a, b = _split_git_header(line[len("diff --git "):])
            cur = FileDiff(_clean(a, "a/"), _clean(b, "b/"), "modified")
            if len(files) >= MAX_FILES:
                raise DiffError(f"diff touches more than {MAX_FILES} files")
            i += 1
            continue
        if line.startswith("--- ") and (cur is None or (not cur.hunks and i + 1 < len(lines) and lines[i + 1].startswith("+++ "))):
            # plain `diff -u` without a git header, or the ---/+++ pair of a git diff
            old = line[4:].split("\t", 1)[0]
            new = lines[i + 1][4:].split("\t", 1)[0] if i + 1 < len(lines) else ""
            if cur is None or cur.hunks:
                finish()
                cur = FileDiff(None, None, "modified")
            cur.old_path, cur.new_path = _clean(old, "a/"), _clean(new, "b/")
            if cur.old_path is None and cur.new_path is not None:
                cur.status = "added"
            elif cur.new_path is None and cur.old_path is not None:
                cur.status = "deleted"
            i += 2
            continue
        if cur is None:
            i += 1                                     # preamble (commit message, `index` lines of other tools)
            continue
        if line.startswith("new file mode"):
            cur.status, cur.old_path = "added", None
        elif line.startswith("deleted file mode"):
            cur.status, cur.new_path = "deleted", None
        elif line.startswith("rename from "):
            cur.status, cur.old_path = "renamed", _clean(line[len("rename from "):], "")
        elif line.startswith("rename to "):
            cur.status, cur.new_path = "renamed", _clean(line[len("rename to "):], "")
        elif line.startswith("similarity index "):
            try:
                cur.similarity = int(line[len("similarity index "):].rstrip("%"))
            except ValueError:
                pass
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            cur.status = "binary"
            if line.startswith("GIT binary patch"):        # skip the encoded payload up to the next file
                i += 1
                while i < len(lines) and not lines[i].startswith("diff --git "):
                    i += 1
                continue
        elif line.startswith("@@"):
            i = _read_hunk(lines, i, cur)
            continue
        i += 1
    finish()
    return files


def _read_hunk(lines: list[str], i: int, f: FileDiff) -> int:
    m = _HUNK.match(lines[i])
    if not m:
        raise DiffError(f"malformed hunk header: {lines[i][:80]!r}")
    os_, ol, ns, nl = int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1)
    h = Hunk(os_, ol, ns, nl)
    old_no, new_no = os_, ns
    left_old, left_new = ol, nl
    i += 1
    in_insert = False
    while i < len(lines) and (left_old > 0 or left_new > 0):
        ln = lines[i]
        tag = ln[:1]
        if tag == "\\":                                   # "\ No newline at end of file"
            h.lines.append(ln)
            i += 1
            continue
        if tag == " " or ln == "":                        # some tools strip the space of empty context lines
            old_no += 1
            new_no += 1
            left_old -= 1
            left_new -= 1
            in_insert = False
        elif tag == "-":
            f.deleted.add(old_no)
            old_no += 1
            left_old -= 1
            in_insert = False
        elif tag == "+":
            f.added.add(new_no)
            if not in_insert:
                f.anchors.add(max(old_no - 1, 0))          # inserted after old line (old_no - 1)
                in_insert = True
            new_no += 1
            left_new -= 1
        else:
            raise DiffError(f"unexpected line in hunk: {ln[:80]!r}")
        h.lines.append(ln)
        i += 1
    if left_old < 0 or left_new < 0 or left_old > 0 or left_new > 0:
        raise DiffError("hunk is shorter or longer than its header says")
    while i < len(lines) and lines[i].startswith("\\"):    # trailing "\ No newline" marker
        h.lines.append(lines[i])
        i += 1
    f.hunks.append(h)
    return i


def apply_patch(old: str, f: FileDiff) -> str:
    """New file contents = old contents + this file's hunks. Every context and deleted line must match exactly, so a
    diff made against a different version of the file is rejected (DiffError) instead of producing nonsense."""
    if f.status in ("binary", "deleted"):
        raise DiffError(f"cannot apply a {f.status} change")
    src = old.split("\n") if old else []          # "".split() would be [""]: one phantom empty line
    trailing_nl = old.endswith("\n")
    if trailing_nl:
        src = src[:-1]
    out: list[str] = []
    pos = 0                                                # next unconsumed old line (0-based)
    new_marker = False                                     # "\ No newline" after a line that exists in the NEW file
    touched_end = False                                    # did the last hunk reach the old file's last line?
    for h in f.hunks:
        start = h.old_start - 1 if h.old_len > 0 else h.old_start   # `-0,0` / `-5,0`: insert after line 5
        if start < pos or start > len(src):
            raise DiffError("hunks overlap or point past the end of the file")
        out.extend(src[pos:start])
        pos = start
        last = ""
        new_marker = False
        for ln in h.lines:
            tag, body = ln[:1], ln[1:]
            if tag == "\\":
                if last in ("+", " ", ""):
                    new_marker = True
                continue
            if tag == " " or ln == "":
                if pos >= len(src) or src[pos] != body:
                    raise DiffError(f"context does not match the base version at line {pos + 1}")
                out.append(src[pos])
                pos += 1
                last = " "
            elif tag == "-":
                if pos >= len(src) or src[pos] != body:
                    raise DiffError(f"deleted line does not match the base version at line {pos + 1}")
                pos += 1
                last = "-"
            elif tag == "+":
                out.append(body)
                last = "+"
        touched_end = pos == len(src)
    out.extend(src[pos:])
    text = "\n".join(out)
    # end of file: if the patch reached it, the marker decides; otherwise the old file's ending is kept
    ends_nl = (not new_marker) if (touched_end or f.status == "added") else trailing_nl
    if out and ends_nl:
        text += "\n"
    return text
