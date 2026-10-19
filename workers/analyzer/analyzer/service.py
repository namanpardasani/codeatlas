"""Internal search service (loopback only). The Node API forwards POST /repos/:id/search here because the
embedding model lives in Python.

    uv run python -m analyzer.service            # listens on 127.0.0.1:$SEARCH_PORT (default 8001)
"""
import json
import logging
import os
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, db
from .embeddings import LazyEmbedder
from .llm import LLMError, get_llm
from .rag.pipeline import answer
from .search import CHUNKINGS, MODES, search

log = logging.getLogger("analyzer.service")
MAX_BODY = 16 * 1024
MAX_QUERY = 500
embedder = LazyEmbedder()
_llm = None
_reranker = None


def llm_client():
    """Built lazily so the service starts (and search works) even when no LLM is configured yet."""
    global _llm
    if _llm is None:
        _llm = get_llm()
    return _llm


def reranker():
    global _reranker
    if config.RAG_RERANK != "cross-encoder":
        return None
    if _reranker is None:
        from .rag.rerank import CrossEncoderReranker
        _reranker = CrossEncoderReranker().scores
    return _reranker


def chat_events(body: dict):
    """Validate a /chat request and yield RAG events (dicts)."""
    try:
        repo_id, question = int(body["repo_id"]), str(body["question"])
    except (KeyError, TypeError, ValueError):
        yield {"type": "error", "kind": "bad_request", "message": "repo_id and question are required"}
        return
    history = []
    for turn in (body.get("history") or [])[-config.RAG_HISTORY_TURNS:]:
        if isinstance(turn, dict):
            history.append((str(turn.get("q", ""))[:500], str(turn.get("a", ""))[:700]))
    client_key = str(body.get("client_key") or "anonymous")[:64]
    try:
        llm = llm_client()
    except LLMError as e:
        yield {"type": "error", **e.to_dict()}
        return
    with db.connect() as conn:
        yield from answer(conn, embedder.get(), llm, repo_id, question, history=history, client_key=client_key,
                          reranker=reranker())


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


class NoReverseDNSServer(ThreadingHTTPServer):
    """http.server.HTTPServer.server_bind() calls socket.getfqdn(host): a reverse DNS lookup that blocks when the
    resolver is flaky (WSL), stalling startup and leaving resolver sockets behind. We only need the address."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[0], self.server_address[1]


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

    def _stream(self, events) -> None:
        """NDJSON stream: one JSON event per line, flushed immediately (the Node API relays it as SSE)."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for ev in events:
                self.wfile.write((json.dumps(ev) + "\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            events.close()  # client went away: stop generating (and record the tokens used so far)
        except Exception:  # noqa: BLE001
            log.exception("chat stream failed")
            try:
                self.wfile.write((json.dumps({"type": "error", "kind": "unavailable", "message": "Internal error"}) + "\n").encode())
            except OSError:
                pass

    def do_POST(self):  # noqa: N802
        if self.path not in ("/search", "/chat"):
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
        if self.path == "/chat":
            return self._stream(chat_events(body))
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
    NoReverseDNSServer((host, config.SEARCH_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
