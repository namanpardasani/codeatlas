"""Run parsing in an isolated child process.

Why: tree-sitter is native C. The Python binding has no parse timeout, and a grammar bug
on hostile input could hang or segfault. In a child process the parent can kill a hung
parse (timeout) and survive a crash, recording a per-file failure instead of dying.
"""
import multiprocessing as mp
import resource

from .. import config
from .types import ParseResult

_ctx = mp.get_context("spawn")  # fresh interpreter: no inherited DB/Redis sockets
MEMORY_LIMIT_BYTES = 2 * 1024**3


def _child(conn, parse_fn_path: str | None):
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    except (ValueError, OSError):
        pass
    if parse_fn_path:
        import importlib
        mod, fn = parse_fn_path.rsplit(":", 1)
        parse = getattr(importlib.import_module(mod), fn)
    else:
        from . import parse_source as parse
    while True:
        msg = conn.recv()
        if msg is None:
            return
        path, source = msg
        try:
            result = parse(path, source)
        except Exception as e:  # noqa: BLE001
            result = ParseResult(status="failed", error=f"{type(e).__name__}: {e}"[:300])
        conn.send(result)


class SandboxedParser:
    def __init__(self, timeout_s: float | None = None, parse_fn: str | None = None):
        self.timeout_s = config.PARSE_TIMEOUT_S if timeout_s is None else timeout_s
        self._parse_fn = parse_fn  # "module:function" (tests inject slow/crashing parsers)
        self._proc = None
        self._conn = None
        self._start()

    def _start(self):
        parent, child = _ctx.Pipe()
        self._proc = _ctx.Process(target=_child, args=(child, self._parse_fn), daemon=True)
        self._proc.start()
        child.close()
        self._conn = parent

    def _kill(self):
        if self._proc is not None and self._proc.is_alive():
            self._proc.kill()
        if self._proc is not None:
            self._proc.join(timeout=5)
        if self._conn is not None:
            self._conn.close()

    def parse(self, path: str, source: bytes) -> ParseResult:
        try:
            self._conn.send((path, source))
            if not self._conn.poll(self.timeout_s):
                self._kill()
                self._start()
                return ParseResult(status="failed", error=f"parse timed out after {self.timeout_s}s")
            return self._conn.recv()
        except (EOFError, BrokenPipeError, ConnectionResetError, OSError):
            self._kill()
            self._start()
            return ParseResult(status="failed", error="parser process crashed")

    def close(self):
        try:
            self._conn.send(None)
        except OSError:
            pass
        self._kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
