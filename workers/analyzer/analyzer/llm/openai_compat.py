"""OpenAI-compatible chat completions with streaming. One adapter covers Ollama, llama.cpp's llama-server,
Groq, OpenRouter, Google Gemini's compatibility endpoint and OpenAI itself: they all speak this protocol."""
import json
import time
from collections.abc import Iterator

import httpx

from .types import Delta, LLMError, Message, Usage, estimate_tokens

RETRY_STATUS = {429, 500, 502, 503, 504}


class OpenAICompatClient:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, *, name: str = "openai_compat",
                 paid: bool = False, connect_timeout: float = 10, read_timeout: float = 120, retries: int = 2,
                 extra_headers: dict | None = None, frequency_penalty: float | None = None):
        self.base_url, self.model, self.name, self.paid = base_url.rstrip("/"), model, name, paid
        self.retries = retries
        self.frequency_penalty = frequency_penalty
        self._timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=15, pool=10)
        self._headers = {"Content-Type": "application/json", **(extra_headers or {})}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    def _raise_for(self, resp: httpx.Response) -> None:
        body = ""
        try:
            body = resp.read().decode("utf8", errors="replace")[:300]
        except httpx.HTTPError:
            pass
        retry_after = None
        if (ra := resp.headers.get("retry-after")) and ra.replace(".", "", 1).isdigit():
            retry_after = float(ra)
        s = resp.status_code
        if s in (401, 403):
            raise LLMError("auth", "The LLM provider rejected the API key (check LLM_API_KEY).")
        if s == 429:
            raise LLMError("rate_limit", "The LLM provider's rate limit was hit; try again shortly.",
                           retryable=True, retry_after=retry_after)
        if s in (400, 404, 413, 422):
            raise LLMError("bad_request", f"The LLM provider rejected the request ({s}): {body}")
        raise LLMError("unavailable", f"The LLM provider returned {s}.", retryable=s in RETRY_STATUS, retry_after=retry_after)

    def stream(self, messages: list[Message], *, max_tokens: int = 700, temperature: float = 0.1) -> Iterator[Delta | Usage]:
        payload = {"model": self.model, "stream": True, "max_tokens": max_tokens, "temperature": temperature,
                   "stream_options": {"include_usage": True},
                   "messages": [{"role": m.role, "content": m.content} for m in messages]}
        if self.frequency_penalty:  # small local models fall into repetition loops without it
            payload["frequency_penalty"] = self.frequency_penalty
        attempt = 0
        while True:
            started = False
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    with client.stream("POST", f"{self.base_url}/chat/completions", headers=self._headers,
                                       json=payload) as resp:
                        if resp.status_code != 200:
                            self._raise_for(resp)
                        out_chars, usage = 0, None
                        for line in resp.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                obj = json.loads(data)
                            except ValueError:
                                continue
                            if obj.get("usage"):
                                usage = Usage(obj["usage"].get("prompt_tokens", 0), obj["usage"].get("completion_tokens", 0))
                            for ch in obj.get("choices") or []:
                                text = (ch.get("delta") or {}).get("content")
                                if text:
                                    started = True
                                    out_chars += len(text)
                                    yield Delta(text)
                        yield usage or Usage(estimate_tokens(" ".join(m.content for m in messages)),
                                             max(1, int(out_chars / 3.5)))
                        return
            except LLMError as e:
                if not e.retryable or started or attempt >= self.retries:
                    raise
                time.sleep(min(e.retry_after or (0.5 * 3 ** attempt), 10))
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                if attempt >= self.retries:
                    raise LLMError("unavailable", f"Cannot reach the LLM at {self.base_url} ({type(e).__name__}).") from e
                time.sleep(0.5 * 3 ** attempt)
            except httpx.ReadTimeout as e:
                raise LLMError("timeout", "The LLM took too long to respond.", retryable=not started) from e
            except httpx.HTTPError as e:
                raise LLMError("unavailable", f"LLM connection failed ({type(e).__name__}).") from e
            attempt += 1
