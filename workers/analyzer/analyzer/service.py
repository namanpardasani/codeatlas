"""Internal search service (loopback only). The Node API forwards POST /repos/:id/search here because the
embedding model lives in Python.

    uv run python -m analyzer.service            # listens on 127.0.0.1:$SEARCH_PORT (default 8001)
"""
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, db
from .embeddings import LazyEmbedder
from .search import CHUNKINGS, MODES, search

log = logging.getLogger("analyzer.service")
MAX_BODY = 16 * 1024
MAX_QUERY = 500
embedder = LazyEmbedder()


def handle_search(body: dict) -> tuple[int, dict]:
    try:
        repo_id = int(body["repo_id"])
        query = str(body["query"]).strip()
    except (KeyError, TypeError, ValueError):
        return 400, {"error": "repo_id and query are required"}
    if not query or len(query) > MAX_QUERY:
        return 400, {"error": f"query must be 1..{MAX_QUERY} characters"}
    mode, chunking = body.get("mode", "hybrid"), body.get("chunking", "ast")
    if mode not in MODES or chunking not in CHUNKINGS:
        return 400, {"error": f"mode must be one of {MODES}, chunking one of {CHUNKINGS}"}
    try:
        limit = int(body.get("limit", 10))
    except (TypeError, ValueError):
        return 400, {"error": "limit must be an integer"}
    opt = lambda k: (str(body[k])[:200] if body.get(k) else None)  # noqa: E731
    with db.connect() as conn:
        result = search(conn, embedder.get() if mode != "keyword" else None, repo_id, query, mode=mode,
                        chunking=chunking, limit=limit, language=opt("language"), path_prefix=opt("path_prefix"),
                        kind=opt("kind"))
    return 200, result.to_dict()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            e = embedder.get()
            return self._send(200, {"ok": True, "model": e.name if e else None, "vector_ready": e is not None})
        self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/search":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413 if length > MAX_BODY else 400, {"error": "bad body size"})
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        try:
            status, payload = handle_search(body)
        except Exception:  # noqa: BLE001
            log.exception("search failed")
            status, payload = 500, {"error": "search failed"}
        self._send(status, payload)

    def log_message(self, fmt, *args):  # quiet access log
        log.debug(fmt, *args)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    host = os.environ.get("SEARCH_HOST", "127.0.0.1")
    embedder.get()  # load the model before accepting traffic
    log.info("search service on %s:%s", host, config.SEARCH_PORT)
    ThreadingHTTPServer((host, config.SEARCH_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
