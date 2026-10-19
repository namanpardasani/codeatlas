from dataclasses import dataclass


@dataclass
class Message:
    role: str      # system | user | assistant
    content: str


@dataclass
class Delta:
    text: str


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


class LLMError(Exception):
    """A provider failure with a stable `kind` the API/UI can act on."""
    KINDS = ("auth", "rate_limit", "quota", "timeout", "unavailable", "bad_request", "paid_not_allowed", "config")

    def __init__(self, kind: str, message: str, *, retryable: bool = False, retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.message, self.retryable, self.retry_after = kind, message, retryable, retry_after

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "retry_after": self.retry_after}


def estimate_tokens(text: str) -> int:
    """Rough token count (~3.5 chars/token for code + prose); only used for budgets, never for billing."""
    return max(1, int(len(text) / 3.5))
