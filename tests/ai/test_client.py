import pytest
from pydantic import BaseModel

from tchekam.ai.client import LLMResult, get_llm_client, strict_json_schema
from tchekam.ai.fake import FakeLLMClient, FakeRefusal
from tchekam.ai.models import AICallLog
from tchekam.ai.schemas import Extraction


class Item(BaseModel):
    name: str
    tags: list[str]


class Outer(BaseModel):
    items: list[Item]
    count: int


def _call(client, purpose="demo", schema_model=Outer, user_text="SECRET-INPUT 677123456"):
    return client.structured(
        purpose=purpose,
        model="deepseek/deepseek-v4.1-flash-1017",
        system="SECRET-SYSTEM",
        user_content=[{"type": "text", "text": user_text}],
        schema_model=schema_model,
        effort="low",
        max_tokens=1024,
        prompt_version="v1",
    )


def _objects(schema):
    """Every object schema in a JSON schema, including $defs."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return found


def test_strict_schema_closes_every_object_and_requires_every_property():
    schema = strict_json_schema(Outer)

    objects = _objects(schema)
    assert len(objects) == 2
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])


def test_extraction_schema_is_strict_and_hides_extraction_failed():
    schema = strict_json_schema(Extraction)

    assert "extraction_failed" not in schema["properties"]
    assert "summary_filtered" not in schema["properties"]
    assert "phone_numbers" in schema["properties"]
    for obj in _objects(schema):
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])


def test_fake_is_the_test_backend_and_a_singleton():
    assert get_llm_client() is FakeLLMClient.instance()


def test_openrouter_backend_selected_by_setting(settings):
    settings.AI_BACKEND = "openrouter"
    settings.OPENROUTER_API_KEY = "test-key"

    client = get_llm_client()

    assert type(client).__name__ == "OpenRouterApplicationClient"
    assert get_llm_client() is client


def test_unknown_backend_raises(settings):
    settings.AI_BACKEND = "oracle"

    with pytest.raises(ValueError):
        get_llm_client()


@pytest.mark.django_db
def test_fake_returns_validated_model_and_logs_the_call(fake_llm):
    fake_llm.responses["demo"] = ['{"items": [{"name": "a", "tags": []}], "count": 1}']

    result = _call(fake_llm)

    assert result == LLMResult(
        ok=True, data=Outer(items=[Item(name="a", tags=[])], count=1), error=None
    )
    log = AICallLog.objects.get()
    assert (log.purpose, log.model, log.prompt_version, log.success, log.error) == (
        "demo",
        "deepseek/deepseek-v4.1-flash-1017",
        "v1",
        True,
        "",
    )
    assert fake_llm.calls[0]["purpose"] == "demo"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "raw",
    ["not json", '{"items": "nope", "count": 1}', '{"count": 1}', "[]"],
)
def test_fake_invalid_output_is_a_failure_result(fake_llm, raw):
    fake_llm.responses["demo"] = [raw]

    result = _call(fake_llm)

    assert result == LLMResult(ok=False, data=None, error="invalid_output")
    assert AICallLog.objects.get().error == "invalid_output"


@pytest.mark.django_db
def test_fake_refusal_and_exceptions_are_failure_results(fake_llm):
    fake_llm.responses["demo"] = [FakeRefusal("cyber"), TimeoutError("boom")]

    first = _call(fake_llm)
    second = _call(fake_llm)
    third = _call(fake_llm)  # queue exhausted

    assert first.error == "refusal:cyber"
    assert second.error == "TimeoutError"
    assert third.error == "no_canned_response"
    assert list(AICallLog.objects.order_by("id").values_list("success", flat=True)) == [
        False,
        False,
        False,
    ]


def test_call_log_has_no_content_fields():
    names = {f.name for f in AICallLog._meta.get_fields()}

    assert names == {
        "id",
        "purpose",
        "model",
        "prompt_version",
        "tokens_in",
        "tokens_out",
        "cache_read_tokens",
        "cache_write_tokens",
        "latency_ms",
        "success",
        "error",
        "request_id",
        "serving_provider",
        "agent_run",
        "call_id",
        "created_at",
    }


@pytest.mark.django_db
def test_call_log_row_contains_no_input_or_output_text(fake_llm):
    fake_llm.responses["demo"] = ['{"items": [{"name": "SECRET-OUTPUT", "tags": []}], "count": 1}']

    _call(fake_llm)

    row = AICallLog.objects.values().get()
    blob = " ".join(str(v) for v in row.values())
    for secret in ("SECRET-INPUT", "SECRET-SYSTEM", "SECRET-OUTPUT", "677123456"):
        assert secret not in blob
