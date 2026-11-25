import json

import httpx
import pytest
from langchain_core.messages import HumanMessage

from tchekam.ai.agent.budget import billed_microusd
from tchekam.ai.agent.execution import claim
from tchekam.ai.agent.models import chat_model
from tchekam.ai.agent.policy import role_policy
from tchekam.ai.agent.schemas import ModelUnavailable
from tchekam.speech.base import get_speech_to_text

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("NaN", None),
        ("Infinity", None),
        (-1, None),
        (0, 0),
        (0.0000201, 21),
        ("0.01", 10000),
    ],
)
def test_billed_cost_rounds_up_and_unknown_cost_is_not_refunded(value, expected):
    assert billed_microusd(value) == expected


def test_pinned_sdk_serializes_nested_provider_policy_without_content_logging(make_run, settings):
    ctx = claim(make_run().pk)
    settings.OPENROUTER_API_KEY = "synthetic-test-key"
    settings.AGENT_ROLE_POLICIES = {
        "chat": {
            "models": ["synthetic/chat"],
            "endpoints": ["synthetic/endpoint"],
            "max_cost_microusd": 10,
            "reasoning": {"effort": "low", "exclude": True},
        }
    }
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "synthetic-id",
                "object": "chat.completion",
                "created": 1,
                "model": "synthetic/chat",
                "system_fingerprint": None,
                "provider": "synthetic/endpoint",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"kind":"clarify","catalog":"number"}',
                        },
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    model = chat_model(ctx, transport=httpx.MockTransport(handler))
    response = model.invoke([HumanMessage(content="synthetic canary")])
    assert response.content
    assert len(sent) == 1
    assert sent[0]["provider"] == {
        "only": ["synthetic/endpoint"],
        "data_collection": "deny",
        "zdr": True,
        "require_parameters": True,
        "allow_fallbacks": False,
    }
    assert not sent[0].get("plugins")
    assert "trace" not in sent[0]
    assert sent[0]["reasoning"] == {"effort": "low", "exclude": True}


def test_sdk_does_not_retry_when_transport_fails(make_run, settings):
    ctx = claim(make_run().pk)
    settings.OPENROUTER_API_KEY = "synthetic-test-key"
    settings.AGENT_ROLE_POLICIES = {
        "chat": {
            "models": ["synthetic/chat"],
            "endpoints": ["synthetic/endpoint"],
            "max_cost_microusd": 10,
        }
    }
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, json={"error": {"code": 503, "message": "synthetic failure"}})

    with pytest.raises(Exception, match="synthetic failure"):
        chat_model(ctx, transport=httpx.MockTransport(handler)).invoke("synthetic")
    assert len(requests) == 1


def test_paid_graph_settles_and_audits_before_transport_cleanup(
    make_run, settings, monkeypatch, fake_channel
):
    from tchekam.ai.agent import graph, models
    from tchekam.ai.models import AgentBudget, AgentReservation, AICallLog

    ctx = claim(make_run().pk)
    settings.OPENROUTER_API_KEY = "synthetic-test-key"
    settings.AGENT_ROLE_POLICIES = {
        "chat": {
            "models": ["synthetic/chat"],
            "endpoints": ["synthetic/endpoint"],
            "max_cost_microusd": 100,
        }
    }

    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": "synthetic-id",
                "object": "chat.completion",
                "created": 1,
                "model": "synthetic/chat",
                "system_fingerprint": None,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"kind":"clarify","catalog":"number"}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 4,
                    "total_tokens": 7,
                    "cost": 0.00002,
                },
            },
        )

    original = models.chat_model
    created = []

    def factory(context, role="chat"):
        model = original(context, role, transport=httpx.MockTransport(handler))
        created.append(model)
        return model

    monkeypatch.setattr(models, "chat_model", factory)
    monkeypatch.setattr(graph, "chat_model", factory)
    result = graph.build_graph(ctx).invoke({"run_id": ctx.run_id})
    assert result["completed"]
    call = AICallLog.objects.get(agent_run_id=ctx.run_id)
    assert call.success and call.request_id == "synthetic-id"
    assert AgentReservation.objects.get(run_id=ctx.run_id).status == "settled"
    assert set(AgentBudget.objects.values_list("used", flat=True)) == {20}
    assert ctx.model_resources == []
    assert all(model._owned_http_client is None for model in created)


def test_unconfigured_role_is_disabled(settings):
    settings.AGENT_ROLE_POLICIES = {"vision": {}}
    with pytest.raises(ModelUnavailable):
        role_policy("vision")


def test_separate_fast_role_is_not_supported(settings):
    settings.AGENT_ROLE_POLICIES = {"fast": {}}
    with pytest.raises(ModelUnavailable, match="unsupported_role"):
        role_policy("fast")


@pytest.mark.parametrize("role", ["chat", "vision"])
def test_selected_model_is_used_when_policy_omits_models(settings, role):
    from tchekam.ai.models import AgentControl

    AgentControl.objects.create(pk=1, vision_enabled=True)
    settings.OPENROUTER_API_KEY = "synthetic-test-key"
    settings.AGENT_ROLE_POLICIES = {
        role: {
            "endpoints": ["synthetic/endpoint"],
            "max_cost_microusd": 10,
        }
    }
    assert role_policy(role)["models"] == ["deepseek/deepseek-v4.1-flash-1017"]


def test_structured_client_defaults_to_vision():
    from tchekam.ai.openrouter_client import OpenRouterClient

    assert OpenRouterClient(context=None).role == "vision"


@pytest.mark.parametrize("served_model", ["synthetic/vision", "unexpected/model"])
def test_structured_vision_records_usage_and_closes_owned_transport(
    make_run, settings, monkeypatch, served_model
):
    from tchekam.ai import openrouter_client
    from tchekam.ai.agent import models
    from tchekam.ai.agent.schemas import ImageObservation
    from tchekam.ai.models import AgentControl, AICallLog

    ctx = claim(make_run().pk)
    AgentControl.objects.filter(pk=1).update(vision_enabled=True)
    settings.OPENROUTER_API_KEY = "synthetic-test-key"
    settings.AGENT_ROLE_POLICIES = {
        "vision": {
            "models": ["synthetic/vision"],
            "endpoints": ["synthetic/endpoint"],
            "max_cost_microusd": 100,
            "reasoning": {"effort": "none", "enabled": False},
        }
    }
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "synthetic-vision",
                "object": "chat.completion",
                "created": 1,
                "model": served_model,
                "provider": "synthetic/provider",
                "system_fingerprint": None,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "numbers": ["+237677123456"],
                                    "amounts_xaf": [],
                                    "uncertain": False,
                                }
                            ),
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                    "cost": 0.00002,
                },
            },
        )

    def factory(context, role):
        return models.chat_model(context, role, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(openrouter_client, "chat_model", factory)
    result = openrouter_client.OpenRouterClient(ctx).structured(
        purpose="agent.vision",
        model="synthetic/vision",
        system="synthetic extraction",
        user_content=[{"type": "text", "text": "synthetic fixture"}],
        schema_model=ImageObservation,
        effort="low",
        max_tokens=512,
        prompt_version="agent-vision-v1",
    )
    if served_model == "synthetic/vision":
        assert result.ok and result.data.numbers == ["+237677123456"]
    else:
        assert not result.ok and result.data is None and result.error == "served_model"
    call = AICallLog.objects.get(agent_run_id=ctx.run_id)
    assert call.request_id == "synthetic-vision"
    assert call.serving_provider == "synthetic/provider"
    assert (call.tokens_in, call.tokens_out) == (10, 20)
    assert sent[0]["max_tokens"] == 512
    assert sent[0]["reasoning"] == {"effort": "none", "enabled": False}
    assert all(model._owned_http_client is None for model in ctx.model_resources)


def test_openrouter_stt_fails_closed_without_a_key(settings):
    settings.SPEECH_BACKEND = "openrouter"
    settings.OPENROUTER_API_KEY = ""
    stt = get_speech_to_text()
    assert not stt.transcribe(b"fake secret audio", "audio/ogg").text
