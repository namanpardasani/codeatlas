"""Language-plugin registry. To add a language: write a LanguagePlugin and list it here."""
import os

from .. import config
from .js_ts import make_plugins as make_js_ts_plugins
from .python_plugin import PythonPlugin
from .types import ParseResult

_BY_EXT: dict[str, object] | None = None
MINIFIED_AVG_LINE = 1000  # average bytes per line above this => minified/generated


def _registry() -> dict:
    global _BY_EXT
    if _BY_EXT is None:
        plugins = [*make_js_ts_plugins(), PythonPlugin()]
        _BY_EXT = {ext: p for p in plugins for ext in p.extensions}
    return _BY_EXT


def supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _registry()


def parse_source(path: str, source: bytes) -> ParseResult:
    """Parse one file. Never raises: failures come back as status failed/skipped."""
    plugin = _registry().get(os.path.splitext(path)[1].lower())
    if plugin is None:
        return ParseResult(status="skipped", error="unsupported language")
    if len(source) > config.MAX_PARSE_BYTES:
        return ParseResult(status="skipped", error=f"file larger than {config.MAX_PARSE_BYTES} bytes")
    lines = source.count(b"\n") + 1
    if len(source) / lines > MINIFIED_AVG_LINE:
        return ParseResult(status="skipped", error="looks minified or generated")
    try:
        return plugin.parse(source)
    except Exception as e:  # defensive: one bad file must never fail the job
        return ParseResult(status="failed", error=f"{type(e).__name__}: {e}"[:300])
