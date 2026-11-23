from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .client import INVALID_OUTPUT, LLMResult, parse_output, record_call


@dataclass(frozen=True)
class FakeRefusal:
    """A canned response that simulates the model declining (stop_reason "refusal")."""

    category: str | None = None


class FakeLLMClient:
    """Canned responses for tests and offline runs, consumed in order per purpose.

    Each queued item is raw model text (parsed and validated like a real response), an exception
    (turned into a failure result, as the real client does) or a FakeRefusal. Calls are logged
    to AICallLog like real ones and recorded in `calls`.
    """

    _instance: "FakeLLMClient | None" = None

    def __init__(self) -> None:
        self.reset()

    @classmethod
    def instance(cls) -> "FakeLLMClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reset(self) -> None:
        self.responses: dict[str, list[str | BaseException | FakeRefusal]] = {}
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "purpose": purpose,
                "model": model,
                "system": system,
                "user_content": user_content,
                "schema_model": schema_model,
                "effort": effort,
                "max_tokens": max_tokens,
                "prompt_version": prompt_version,
                "use_fallback": use_fallback,
            }
        )
        queue = self.responses.get(purpose) or []
        item = queue.pop(0) if queue else None
        data = None
        if item is None:
            error = "no_canned_response"
        elif isinstance(item, FakeRefusal):
            error = f"refusal:{item.category or 'unknown'}"
        elif isinstance(item, BaseException):
            error = type(item).__name__
        else:
            data = parse_output(item, schema_model)
            error = None if data is not None else INVALID_OUTPUT
        record_call(
            purpose=purpose, model=model, prompt_version=prompt_version, latency_ms=0, error=error
        )
        return LLMResult(ok=error is None, data=data, error=error)
