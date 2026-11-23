"""The LLM boundary: everything outside this app talks to Claude through here."""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from django.conf import settings
from pydantic import BaseModel, ValidationError

from .models import AICallLog

INVALID_OUTPUT = "invalid_output"


@dataclass(frozen=True)
class LLMResult:
    ok: bool
    data: BaseModel | None = None
    error: str | None = None  # see AICallLog.error for the values


class LLMClient(Protocol):
    def structured(
        self,
        *,
        purpose: str,
        model: str,
        system: str,
        user_content: list[dict[str, Any]],
        schema_model: type[BaseModel],
        effort: str,
        max_tokens: int,
        prompt_version: str,
        use_fallback: bool,
    ) -> LLMResult:
        """One structured-output call. Never raises for provider failures; logs an AICallLog."""
        ...


def get_llm_client() -> LLMClient:
    backend = settings.AI_BACKEND
    if backend == "fake":
        from .fake import FakeLLMClient

        return FakeLLMClient.instance()
    if backend == "anthropic":
        return _anthropic_client(settings.ANTHROPIC_API_KEY)
    raise ValueError(f"Unknown AI_BACKEND: {backend!r}")


@lru_cache(maxsize=4)
def _anthropic_client(api_key: str) -> LLMClient:
    # One instance per key so the SDK's connection pool is reused across calls.
    from .anthropic_client import AnthropicClient

    return AnthropicClient(api_key=api_key)


def strict_json_schema(schema_model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema in the strict form structured outputs need.

    Every object is closed (additionalProperties: false) and lists all its properties as required.
    """
    schema = schema_model.model_json_schema()

    def tighten(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("title"), str):
                del node["title"]
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                tighten(value)
        elif isinstance(node, list):
            for value in node:
                tighten(value)

    tighten(schema)
    return schema


def parse_output(text: str, schema_model: type[BaseModel]) -> BaseModel | None:
    """Validate raw model text against the schema; None if it is not valid JSON or does not fit."""
    try:
        return schema_model.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError, TypeError):
        return None


def record_call(
    *,
    purpose: str,
    model: str,
    prompt_version: str,
    latency_ms: int,
    error: str | None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    request_id: str = "",
) -> None:
    AICallLog.objects.create(
        purpose=purpose,
        model=model,
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        latency_ms=latency_ms,
        success=error is None,
        error=error or "",
        request_id=request_id,
    )
