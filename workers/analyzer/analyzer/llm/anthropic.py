"""Claude via the Anthropic Messages API (streaming). PAID: only constructed when LLM_ALLOW_PAID=1."""
import json
import time
from collections.abc import Iterator

import httpx

from .types import Delta, LLMError, Message, Usage, estimate_tokens


class AnthropicClient:
    name = "anthropic"
    paid = True

    def __init__(self, api_key: str, model: str, *, base_url: str = "https://api.anthropic.com", retries: int = 2,
                 read_timeout: float = 120):
        self.model, self.base_url, self.retries = model, base_url.rstrip("/"), retries
        self._timeout = httpx.Timeout(connect=10, read=read_timeout, write=15, pool=10)
        self._headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}

    def stream(self, messages: list[Message], *, max_tokens: int = 700, temperature: float = 0.1) -> Iterator[Delta | Usage]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        payload = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "stream": True,
                   "messages": [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]}
        if system:
            payload["system"] = system
        attempt = 0
        while True:
            started = False
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    with client.stream("POST", f"{self.base_url}/v1/messages", headers=self._headers, json=payload) as r:
                        if r.status_code != 200:
                            r.read()
                            s = r.status_code
                            kind = {401: "auth", 403: "auth", 429: "rate_limit", 400: "bad_request"}.get(s, "unavailable")
                            raise LLMError(kind, f"Anthropic API returned {s}.", retryable=s in (429, 500, 502, 503, 529))
                        tin = tout = 0
                        out_chars = 0
                        for line in r.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            try:
                                ev = json.loads(line[5:].strip())
                            except ValueError:
                                continue
                            t = ev.get("type")
                            if t == "message_start":
                                tin = (ev.get("message", {}).get("usage") or {}).get("input_tokens", 0)
                            elif t == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                                started = True
                                out_chars += len(ev["delta"]["text"])
                                yield Delta(ev["delta"]["text"])
                            elif t == "message_delta":
                                tout = (ev.get("usage") or {}).get("output_tokens", tout)
                            elif t == "error":
                                raise LLMError("unavailable", "Anthropic stream error.")
                        yield Usage(tin or estimate_tokens(system), tout or max(1, int(out_chars / 3.5)))
                        return
            except LLMError as e:
                if not e.retryable or started or attempt >= self.retries:
                    raise
                time.sleep(0.5 * 3 ** attempt)
            except httpx.TimeoutException as e:
                raise LLMError("timeout", "The LLM took too long to respond.") from e
            except httpx.HTTPError as e:
                if attempt >= self.retries:
                    raise LLMError("unavailable", f"Cannot reach Anthropic ({type(e).__name__}).") from e
                time.sleep(0.5 * 3 ** attempt)
            attempt += 1
