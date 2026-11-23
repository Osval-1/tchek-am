from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from tchekam.ai.anthropic_client import AnthropicClient
from tchekam.ai.models import AICallLog

pytestmark = pytest.mark.django_db


class Answer(BaseModel):
    label: str


def _response(text='{"label": "ok"}', stop_reason="end_turn", category=None, model=None):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if stop_reason == "refusal" else None,
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=30,
            cache_read_input_tokens=1000,
            cache_creation_input_tokens=None,
        ),
        model=model or "claude-sonnet-5-5",
        _request_id="req_123",
    )


class Stub:
    def __init__(self, result):
        self.result = result
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.fixture
def client():
    return AnthropicClient(api_key="test-key")


@pytest.fixture
def plain(client, monkeypatch):
    stub = Stub(_response())
    monkeypatch.setattr(client.sdk.messages, "create", stub)
    return stub


@pytest.fixture
def beta(client, monkeypatch):
    stub = Stub(_response())
    monkeypatch.setattr(client.sdk.beta.messages, "create", stub)
    return stub


def _call(client, use_fallback=False, model="claude-sonnet-5-5", effort="medium"):
    return client.structured(
        purpose="evidence_extraction",
        model=model,
        system="SYSTEM PROMPT",
        user_content=[
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ""}},
            {"type": "text", "text": "hello"},
        ],
        schema_model=Answer,
        effort=effort,
        max_tokens=4096,
        prompt_version="v1",
        use_fallback=use_fallback,
    )


def test_client_is_configured_with_timeout_retries_and_key(client):
    assert client.sdk.api_key == "test-key"
    assert client.sdk.max_retries == 2
    assert client.sdk.timeout == 60.0


def test_plain_request_shape(client, plain):
    result = _call(client, model="claude-haiku-5-5", effort="low")

    assert result.ok and result.data == Answer(label="ok")
    kw = plain.kwargs
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["max_tokens"] == 4096
    assert kw["system"] == [
        {"type": "text", "text": "SYSTEM PROMPT", "cache_control": {"type": "ephemeral"}}
    ]
    [message] = kw["messages"]
    assert message["role"] == "user"
    assert [block["type"] for block in message["content"]] == ["image", "text"]
    assert kw["output_config"]["effort"] == "low"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["format"]["schema"]["additionalProperties"] is False
    for forbidden in (
        "thinking",
        "temperature",
        "top_p",
        "top_k",
        "tool_choice",
        "betas",
        "fallbacks",
    ):
        assert forbidden not in kw


def test_fallback_uses_beta_endpoint_with_default_fallbacks(client, plain, beta):
    result = _call(client, use_fallback=True)

    assert result.ok
    assert plain.kwargs is None
    assert beta.kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert beta.kwargs["fallbacks"] == "default"
    assert beta.kwargs["output_config"]["effort"] == "medium"
    assert "thinking" not in beta.kwargs


def test_successful_call_logs_usage_and_served_model(client, beta):
    beta.result = _response(model="claude-sonnet-5")

    _call(client, use_fallback=True)

    log = AICallLog.objects.get()
    assert log.model == "claude-sonnet-5"
    assert (log.tokens_in, log.tokens_out, log.cache_read_tokens, log.cache_write_tokens) == (
        120,
        30,
        1000,
        0,
    )
    assert log.request_id == "req_123"
    assert log.success is True
    assert log.latency_ms >= 0


def test_refusal_is_a_failure_and_content_is_not_read(client, beta):
    beta.result = _response(text="not json", stop_reason="refusal", category="cyber")

    result = _call(client, use_fallback=True)

    assert (result.ok, result.data, result.error) == (False, None, "refusal:cyber")
    assert AICallLog.objects.get().error == "refusal:cyber"


def test_max_tokens_is_a_failure(client, plain):
    plain.result = _response(text='{"label": "o', stop_reason="max_tokens")

    result = _call(client)

    assert result.error == "max_tokens"


def test_invalid_json_is_invalid_output(client, plain):
    plain.result = _response(text="Sure! here you go")

    assert _call(client).error == "invalid_output"


_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("exc", "name"),
    [
        (
            anthropic.RateLimitError(
                "slow down", response=httpx2.Response(429, request=_REQUEST), body=None
            ),
            "RateLimitError",
        ),
        (
            anthropic.InternalServerError(
                "oops", response=httpx2.Response(500, request=_REQUEST), body=None
            ),
            "InternalServerError",
        ),
        (anthropic.APIConnectionError(request=_REQUEST), "APIConnectionError"),
        (anthropic.APITimeoutError(request=_REQUEST), "APITimeoutError"),
        (
            anthropic.APIResponseValidationError(
                response=httpx2.Response(200, request=_REQUEST), body=None
            ),
            "APIResponseValidationError",
        ),
        (anthropic.APIError("odd", request=_REQUEST, body=None), "APIError"),
        (anthropic.AnthropicError("generic"), "AnthropicError"),
    ],
)
def test_sdk_errors_become_failure_results(client, plain, exc, name):
    plain.result = exc

    result = _call(client)

    assert (result.ok, result.error) == (False, name)
    log = AICallLog.objects.get()
    assert (log.success, log.error, log.model, log.tokens_in) == (
        False,
        name,
        "claude-sonnet-5-5",
        0,
    )
