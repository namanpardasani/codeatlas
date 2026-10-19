"""A tiny local server that speaks the OpenAI-compatible and Anthropic streaming protocols, with scriptable failures."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeProvider:
    def __init__(self):
        self.behaviors: list = []      # consumed one per request: "ok" | ("status", code[, headers]) | "slow" | "drop"
        self.requests: list[dict] = []
        self.text = ["Hello", " from", " the", " model"]
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
                beh = outer.behaviors.pop(0) if outer.behaviors else "ok"
                if isinstance(beh, tuple):
                    self.send_response(beh[1])
                    for k, v in (beh[2] if len(beh) > 2 else {}).items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                if beh == "slow":
                    time.sleep(2)
                    return
                if self.path.endswith("/messages"):
                    self._anthropic(beh)
                else:
                    self._openai(beh)

            def _w(self, s: str):
                self.wfile.write(s.encode())
                self.wfile.flush()

            def _openai(self, beh):
                for i, t in enumerate(outer.text):
                    self._w("data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) + "\n\n")
                    if beh == "drop" and i == 1:
                        return  # connection closes mid-stream, no [DONE]
                self._w("data: " + json.dumps({"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 4}}) + "\n\n")
                self._w("data: [DONE]\n\n")

            def _anthropic(self, beh):
                self._w('event: message_start\ndata: ' + json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 21}}}) + "\n\n")
                for t in outer.text:
                    self._w("event: content_block_delta\ndata: " + json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}}) + "\n\n")
                self._w("event: message_delta\ndata: " + json.dumps({"type": "message_delta", "usage": {"output_tokens": 7}}) + "\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
