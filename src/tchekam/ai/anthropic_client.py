"""Claude via the official SDK. The only module that imports `anthropic`."""

import logging
import time
from typing import Any

import anthropic
from pydantic import BaseModel

from .client import INVALID_OUTPUT, LLMResult, parse_output, record_call, strict_json_schema

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicClient:
    def __init__(self, api_key: str) -> None:
        # The SDK retries 408/409/429/5xx and connection errors itself.
        self.sdk = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=2)

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
        # No thinking/temperature/top_p/top_k, prefill or forced tool_choice: all rejected or
        # unsupported on the 5.5 models. Thinking runs adaptive by default; effort steers it.
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            # Stable prompt only, so the prefix caches; volatile values go in the user message.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_content}],
            "output_config": {
                "format": {"type": "json_schema", "schema": strict_json_schema(schema_model)},
                "effort": effort,
            },
        }
        started = time.monotonic()
        try:
            if use_fallback:
                response = self.sdk.beta.messages.create(
                    **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = self.sdk.messages.create(**kwargs)
        # Most specific first. Every handler records the class name only: SDK messages can
        # echo request content.
        except anthropic.RateLimitError as exc:
            return self._failed(purpose, model, prompt_version, started, exc, exc.status_code)
        except anthropic.APIStatusError as exc:
            return self._failed(purpose, model, prompt_version, started, exc, exc.status_code)
        except anthropic.APIConnectionError as exc:
            return self._failed(purpose, model, prompt_version, started, exc, None)
        except anthropic.APIError as exc:  # e.g. APIResponseValidationError
            return self._failed(purpose, model, prompt_version, started, exc, None)
        except anthropic.AnthropicError as exc:
            return self._failed(purpose, model, prompt_version, started, exc, None)

        data = None
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) or "unknown"
            error = f"refusal:{category}"
            logger.warning("LLM refusal purpose=%s category=%s", purpose, category)
        elif response.stop_reason == "max_tokens":
            error = "max_tokens"
            logger.warning("LLM hit max_tokens purpose=%s", purpose)
        else:
            text = next((b.text for b in response.content if b.type == "text"), None)
            data = parse_output(text, schema_model) if text is not None else None
            error = None if data is not None else INVALID_OUTPUT

        usage = response.usage
        record_call(
            purpose=purpose,
            model=response.model,
            prompt_version=prompt_version,
            latency_ms=_elapsed_ms(started),
            error=error,
            tokens_in=usage.input_tokens or 0,
            tokens_out=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
            request_id=getattr(response, "_request_id", None) or "",
        )
        return LLMResult(ok=error is None, data=data, error=error)

    @staticmethod
    def _failed(
        purpose: str,
        model: str,
        prompt_version: str,
        started: float,
        exc: Exception,
        status: int | None,
    ) -> LLMResult:
        error = type(exc).__name__
        # Class and status only: SDK error messages can echo request content.
        logger.warning("LLM call failed purpose=%s error=%s status=%s", purpose, error, status)
        record_call(
            purpose=purpose,
            model=model,
            prompt_version=prompt_version,
            latency_ms=_elapsed_ms(started),
            error=error,
        )
        return LLMResult(ok=False, error=error)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
