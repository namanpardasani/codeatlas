"""Provider-agnostic LLM access. Select with env vars:

    LLM_PROVIDER = fake | ollama | llamacpp | groq | openrouter | gemini | openai_compat | anthropic
    LLM_MODEL, LLM_API_KEY, LLM_BASE_URL (optional override), LLM_MAX_TOKENS, LLM_TIMEOUT_S

Only `anthropic` (and an openai_compat endpoint on api.openai.com) can cost money, and they refuse to start
unless LLM_ALLOW_PAID=1. The free choices: local (ollama / llamacpp) or a hosted free tier (groq / openrouter /
gemini: you create the key; each provider enforces its own rate limits, surfaced here as `rate_limit` errors)."""
import os
from typing import Protocol

from .. import config
from .anthropic import AnthropicClient
from .fake import FakeLLM
from .openai_compat import OpenAICompatClient
from .types import Delta, LLMError, Message, Usage, estimate_tokens

PRESETS = {  # provider -> (base_url, default_model, needs_key)
    "ollama": ("http://127.0.0.1:11434/v1", "qwen2.5-coder:1.5b", False),
    "llamacpp": ("http://127.0.0.1:8080/v1", "local", False),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant", True),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free", True),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash-lite", True),
}


class LLMClient(Protocol):
    name: str
    model: str
    paid: bool

    def stream(self, messages: list[Message], *, max_tokens: int = ..., temperature: float = ...): ...


def get_llm(env: dict | None = None) -> LLMClient:
    env = os.environ if env is None else env
    provider = env.get("LLM_PROVIDER", "fake")
    allow_paid = env.get("LLM_ALLOW_PAID") == "1"
    key = env.get("LLM_API_KEY")
    timeout = float(env.get("LLM_TIMEOUT_S", config.LLM_TIMEOUT_S))
    if provider == "fake":
        return FakeLLM()
    if provider == "anthropic":
        if not allow_paid:
            raise LLMError("paid_not_allowed", "LLM_PROVIDER=anthropic bills your Anthropic account. "
                                               "Set LLM_ALLOW_PAID=1 to confirm you accept that.")
        if not key:
            raise LLMError("config", "LLM_API_KEY is required for anthropic.")
        return AnthropicClient(key, env.get("LLM_MODEL", "claude-haiku-5-5"), read_timeout=timeout)
    if provider in PRESETS or provider == "openai_compat":
        base, model, needs_key = PRESETS.get(provider, (None, None, False))  # generic endpoint: key optional
        base = env.get("LLM_BASE_URL", base)
        model = env.get("LLM_MODEL", model)
        if not base or not model:
            raise LLMError("config", "openai_compat needs LLM_BASE_URL and LLM_MODEL.")
        paid = "api.openai.com" in base
        if paid and not allow_paid:
            raise LLMError("paid_not_allowed", "This endpoint bills your account. Set LLM_ALLOW_PAID=1 to confirm.")
        if needs_key and not key:
            raise LLMError("config", f"LLM_API_KEY is required for {provider} (create a free key at the provider).")
        return OpenAICompatClient(base, model, key, name=provider, paid=paid, read_timeout=timeout)
    raise LLMError("config", f"Unknown LLM_PROVIDER {provider!r}.")


__all__ = ["Delta", "FakeLLM", "LLMClient", "LLMError", "Message", "Usage", "estimate_tokens", "get_llm"]
