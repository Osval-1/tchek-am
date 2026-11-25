import json

import httpx
import pytest
from pydantic import BaseModel

from tchekam.ai.models import AICallLog
from tchekam.ai.openrouter_client import OpenRouterApplicationClient

pytestmark = pytest.mark.django_db


class Label(BaseModel):
    label: str


def call(handler, settings):
    settings.OPENROUTER_API_KEY = "synthetic-key"
    return OpenRouterApplicationClient(transport=httpx.MockTransport(handler)).structured(
        purpose="test",
        model=settings.OPENROUTER_MODEL,
        system="private-system",
        user_content=[{"type": "text", "text": "private-message"}],
        schema_model=Label,
        effort="low",
        max_tokens=1024,
        prompt_version="v1",
    )


def response(settings, *, text='{"label":"ok"}', model=None, finish="stop", refusal=None):
    return {
        "id": "request-1",
        "provider": "Together",
        "model": model or settings.OPENROUTER_MODEL,
        "choices": [{"finish_reason": finish, "message": {"content": text, "refusal": refusal}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_all_application_calls_use_openrouter_and_strict_private_routing(settings):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response(settings))

    result = call(handler, settings)
    assert result.ok and result.data.label == "ok"
    (request,) = requests
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer synthetic-key"
    body = json.loads(request.content)
    assert body["model"] == "deepseek/deepseek-v4.1-flash-1017"
    assert body["provider"] == {
        "only": ["together/us"],
        "data_collection": "deny",
        "zdr": True,
        "require_parameters": True,
        "allow_fallbacks": False,
    }
    assert body["response_format"]["json_schema"]["strict"]
    assert not body["response_format"]["json_schema"]["schema"]["additionalProperties"]
    assert body["plugins"] == [] and "fallbacks" not in body
    row = AICallLog.objects.get()
    assert row.success and row.request_id == "request-1" and row.serving_provider == "Together"
    assert (row.tokens_in, row.tokens_out) == (10, 5)
    assert "private" not in json.dumps(list(AICallLog.objects.values()), default=str)


@pytest.mark.parametrize(
    "overrides,error",
    [
        ({"text": "not JSON"}, "invalid_output"),
        ({"text": '{"other":true}'}, "invalid_output"),
        ({"refusal": "private-refusal"}, "refusal"),
        ({"finish": "length"}, "max_tokens"),
        ({"finish": "content_filter"}, "invalid_output"),
        ({"model": "unexpected/model"}, "served_model"),
    ],
)
def test_unsafe_or_incomplete_responses_are_rejected(settings, overrides, error):
    result = call(lambda r: httpx.Response(200, json=response(settings, **overrides)), settings)
    assert not result.ok and result.data is None and result.error == error
    assert not AICallLog.objects.get().success


def test_provider_outage_is_not_retried_or_logged_with_content(settings):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(503, text="private-body synthetic-key")

    result = call(handler, settings)
    assert not result.ok and result.error == "HTTPStatusError:503" and len(seen) == 1
    assert "private" not in json.dumps(list(AICallLog.objects.values()), default=str)
