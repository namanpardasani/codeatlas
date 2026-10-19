import pytest

from analyzer import config, db
from analyzer.llm import FakeLLM, LLMError, Message, get_llm
from analyzer.llm.anthropic import AnthropicClient
from analyzer.llm.openai_compat import OpenAICompatClient
from analyzer.llm.types import Delta, Usage
from analyzer.llm import usage as usage_mod

from llm_server import FakeProvider

MSGS = [Message("system", "be brief"), Message("user", "hi")]


@pytest.fixture
def provider():
    p = FakeProvider()
    yield p
    p.close()


def collect(client, **kw):
    text, usage = "", None
    for ev in client.stream(MSGS, **kw):
        if isinstance(ev, Delta):
            text += ev.text
        elif isinstance(ev, Usage):
            usage = ev
    return text, usage


def client(p, **kw):
    return OpenAICompatClient(p.url, "m1", "sk-test", read_timeout=kw.pop("read_timeout", 5), **kw)


def test_streams_deltas_and_reports_provider_usage(provider):
    text, usage = collect(client(provider))
    assert text == "Hello from the model" and (usage.input_tokens, usage.output_tokens) == (11, 4)
    sent = provider.requests[0]
    assert sent["path"] == "/chat/completions" and sent["body"]["model"] == "m1" and sent["body"]["stream"] is True
    assert sent["body"]["max_tokens"] == 700 or "max_tokens" in sent["body"]
    assert sent["headers"]["Authorization"] == "Bearer sk-test"
    assert [m["role"] for m in sent["body"]["messages"]] == ["system", "user"]


def test_no_auth_header_for_local_models(provider):
    c = OpenAICompatClient(provider.url, "local", None)
    collect(c)
    assert "Authorization" not in provider.requests[0]["headers"]


def test_rate_limit_is_retried_honouring_retry_after_then_succeeds(provider):
    provider.behaviors = [("status", 429, {"Retry-After": "0"}), "ok"]
    text, _ = collect(client(provider))
    assert text == "Hello from the model" and len(provider.requests) == 2


def test_auth_failure_is_not_retried_and_is_clearly_labelled(provider):
    provider.behaviors = [("status", 401)]
    with pytest.raises(LLMError) as e:
        collect(client(provider))
    assert e.value.kind == "auth" and "LLM_API_KEY" in e.value.message and len(provider.requests) == 1


def test_persistent_server_errors_give_up_after_the_retry_budget(provider):
    provider.behaviors = [("status", 503)] * 5
    with pytest.raises(LLMError) as e:
        collect(client(provider, retries=2))
    assert e.value.kind == "unavailable" and len(provider.requests) == 3   # 1 try + 2 retries


def test_bad_request_is_not_retried(provider):
    provider.behaviors = [("status", 400)]
    with pytest.raises(LLMError) as e:
        collect(client(provider))
    assert e.value.kind == "bad_request" and len(provider.requests) == 1


def test_read_timeout_becomes_a_timeout_error(provider):
    provider.behaviors = ["slow"]
    with pytest.raises(LLMError) as e:
        collect(client(provider, read_timeout=0.4))
    assert e.value.kind == "timeout"


def test_unreachable_host_is_a_clear_error_after_retries():
    c = OpenAICompatClient("http://127.0.0.1:9", "m", None, retries=1)
    with pytest.raises(LLMError) as e:
        collect(c)
    assert e.value.kind == "unavailable" and "127.0.0.1:9" in e.value.message


def test_mid_stream_drop_is_not_retried_and_keeps_what_arrived(provider):
    provider.behaviors = ["drop"]
    text, usage = collect(client(provider))
    assert text == "Hello from" and usage.output_tokens >= 1 and len(provider.requests) == 1   # no duplicate retry


def test_anthropic_adapter_parses_the_messages_stream(provider):
    c = AnthropicClient("key", "claude-test", base_url=provider.url)
    text, usage = collect(c)
    assert text == "Hello from the model" and (usage.input_tokens, usage.output_tokens) == (21, 7)
    sent = provider.requests[0]
    assert sent["path"] == "/v1/messages" and sent["body"]["system"] == "be brief"
    assert [m["role"] for m in sent["body"]["messages"]] == ["user"]
    assert sent["headers"]["x-api-key"] == "key"


def test_fake_llm_scripted_and_extractive():
    f = FakeLLM(script=["scripted answer"])
    assert collect(f)[0] == "scripted answer"
    ctx = Message("user", "CONTEXT\n[C1] src/a.py:10-20 (function f)\n  10| code\nQUESTION: x")
    assert "couldn't find" in collect(FakeLLM())[0]                   # no context chunks in the prompt -> refuses
    out = "".join(e.text for e in FakeLLM().stream([ctx]) if isinstance(e, Delta))
    assert "[C1:10-20]" in out and "src/a.py" in out


# ---- provider selection and the "never cost money by accident" guard -----------------------------
def test_provider_selection_from_env():
    assert get_llm({"LLM_PROVIDER": "fake"}).name == "fake"
    o = get_llm({"LLM_PROVIDER": "ollama"})
    assert (o.name, o.base_url, o.paid) == ("ollama", "http://127.0.0.1:11434/v1", False)
    g = get_llm({"LLM_PROVIDER": "groq", "LLM_API_KEY": "k", "LLM_MODEL": "x"})
    assert g.base_url == "https://api.groq.com/openai/v1" and g.model == "x"
    c = get_llm({"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "http://localhost:1234/v1", "LLM_MODEL": "m"})
    assert c.base_url == "http://localhost:1234/v1"


@pytest.mark.parametrize("env,kind", [
    ({"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "k"}, "paid_not_allowed"),
    ({"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "https://api.openai.com/v1", "LLM_MODEL": "m", "LLM_API_KEY": "k"}, "paid_not_allowed"),
    ({"LLM_PROVIDER": "anthropic", "LLM_ALLOW_PAID": "1"}, "config"),
    ({"LLM_PROVIDER": "groq"}, "config"),
    ({"LLM_PROVIDER": "openai_compat"}, "config"),
    ({"LLM_PROVIDER": "nope"}, "config"),
])
def test_misconfiguration_and_paid_providers_fail_loudly(env, kind):
    with pytest.raises(LLMError) as e:
        get_llm(env)
    assert e.value.kind == kind


def test_paid_provider_works_only_with_explicit_consent():
    c = get_llm({"LLM_PROVIDER": "anthropic", "LLM_API_KEY": "k", "LLM_ALLOW_PAID": "1"})
    assert c.name == "anthropic" and c.paid is True and c.model.startswith("claude-")


# ---- daily usage caps (database) -------------------------------------------------------------------
try:
    conn = db.connect()
except Exception:  # noqa: BLE001
    conn = None
needs_db = pytest.mark.skipif(conn is None, reason="Postgres not available")


@pytest.fixture
def clean_usage():
    conn.execute("DELETE FROM llm_usage WHERE client_key LIKE 'test-%'")
    yield
    conn.execute("DELETE FROM llm_usage WHERE client_key LIKE 'test-%'")


@needs_db
def test_request_cap_blocks_after_n_questions(clean_usage, monkeypatch):
    monkeypatch.setattr(config, "LLM_DAILY_REQUESTS", 3)
    for _ in range(3):
        usage_mod.reserve(conn, "test-a")
    with pytest.raises(LLMError) as e:
        usage_mod.reserve(conn, "test-a")
    assert e.value.kind == "quota" and e.value.retry_after and 0 < e.value.retry_after <= 86400
    usage_mod.reserve(conn, "test-b")                      # another client is unaffected


@needs_db
def test_token_cap_blocks_even_with_requests_left(clean_usage, monkeypatch):
    monkeypatch.setattr(config, "LLM_DAILY_TOKENS", 1000)
    usage_mod.reserve(conn, "test-c")
    usage_mod.record(conn, "test-c", 700, 400)             # 1100 tokens used
    with pytest.raises(LLMError) as e:
        usage_mod.reserve(conn, "test-c")
    assert e.value.kind == "quota"


@needs_db
def test_global_budget_protects_the_whole_service(clean_usage, monkeypatch):
    usage_mod.reserve(conn, "test-d")
    usage_mod.record(conn, "test-d", 500, 500)
    monkeypatch.setattr(config, "LLM_GLOBAL_DAILY_TOKENS", conn.execute(
        "SELECT sum(input_tokens + output_tokens) FROM llm_usage WHERE day = current_date").fetchone()[0])
    with pytest.raises(LLMError):
        usage_mod.reserve(conn, "test-e")
    assert conn.execute("SELECT requests FROM llm_usage WHERE client_key='test-e' AND day=current_date").fetchone()[0] == 0


def test_frequency_penalty_is_sent_only_when_configured(provider):
    collect(OpenAICompatClient(provider.url, "m", None))
    assert "frequency_penalty" not in provider.requests[-1]["body"]
    collect(OpenAICompatClient(provider.url, "m", None, frequency_penalty=0.4))
    assert provider.requests[-1]["body"]["frequency_penalty"] == 0.4


def test_local_providers_default_to_a_repetition_penalty_hosted_ones_do_not():
    assert get_llm({"LLM_PROVIDER": "llamacpp"}).frequency_penalty == 0.4
    assert get_llm({"LLM_PROVIDER": "ollama"}).frequency_penalty == 0.4
    assert get_llm({"LLM_PROVIDER": "groq", "LLM_API_KEY": "k"}).frequency_penalty is None
    assert not get_llm({"LLM_PROVIDER": "llamacpp", "LLM_FREQUENCY_PENALTY": "0"}).frequency_penalty      # 0 = disabled
