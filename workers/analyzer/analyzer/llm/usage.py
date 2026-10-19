"""Per-client daily LLM budget. Checked BEFORE every call so a runaway client cannot spend the provider's
free tier (or your money) for everyone."""
from datetime import datetime, timedelta, timezone

from .. import config
from .types import LLMError


def _reset_in() -> float:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


def reserve(conn, client_key: str) -> None:
    """Atomically count one request for today, or raise LLMError('quota')."""
    row = conn.execute(
        """INSERT INTO llm_usage (day, client_key, requests) VALUES (current_date, %(k)s, 1)
           ON CONFLICT (day, client_key) DO UPDATE SET requests = llm_usage.requests + 1
           WHERE llm_usage.requests < %(req)s AND llm_usage.input_tokens + llm_usage.output_tokens < %(tok)s
           RETURNING requests""",
        {"k": client_key, "req": config.LLM_DAILY_REQUESTS, "tok": config.LLM_DAILY_TOKENS}).fetchone()
    if row is None:
        raise LLMError("quota", f"Daily limit reached ({config.LLM_DAILY_REQUESTS} questions or "
                                f"{config.LLM_DAILY_TOKENS:,} tokens per day). It resets at 00:00 UTC.",
                       retry_after=_reset_in())
    total = conn.execute("SELECT coalesce(sum(input_tokens + output_tokens), 0) FROM llm_usage WHERE day = current_date").fetchone()[0]
    if total >= config.LLM_GLOBAL_DAILY_TOKENS:
        conn.execute("UPDATE llm_usage SET requests = requests - 1 WHERE day = current_date AND client_key = %s", (client_key,))
        raise LLMError("quota", "The service's shared daily LLM budget is used up. It resets at 00:00 UTC.",
                       retry_after=_reset_in())


def record(conn, client_key: str, input_tokens: int, output_tokens: int) -> None:
    conn.execute("UPDATE llm_usage SET input_tokens = input_tokens + %s, output_tokens = output_tokens + %s "
                 "WHERE day = current_date AND client_key = %s", (input_tokens, output_tokens, client_key))
