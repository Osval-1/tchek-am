"""Scoped OpenRouter structured extraction, without changing existing production factories."""

from time import monotonic
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import tracing_context

from tchekam.ai.agent.budget import billed_microusd, reserve, settle
from tchekam.ai.agent.models import chat_model, close_model
from tchekam.ai.agent.policy import authorize, consume, role_policy
from tchekam.ai.client import LLMResult, parse_output, record_call, strict_json_schema


class OpenRouterClient:
    def __init__(self, context, role="vision"):
        self.context, self.role = context, role

    def structured(
        self,
        *,
        purpose,
        model,
        system,
        user_content,
        schema_model,
        effort,
        max_tokens,
        prompt_version,
        use_fallback,
    ):
        ctx, started, call_id = self.context, monotonic(), uuid4().hex
        reservation, error, parsed = None, "unavailable", None
        actual_cost = None
        tokens_in, tokens_out = 0, 0
        request_id, serving_provider = "", ""
        client = None
        try:
            from django.conf import settings

            authorize(ctx)
            policy = role_policy(self.role)
            if model not in policy["models"] or max_tokens > settings.AGENT_MAX_OUTPUT_TOKENS:
                return LLMResult(ok=False, error="invalid_output")
            consume(ctx, "model_calls")
            reservation = reserve(ctx, call_id, policy["max_cost_microusd"])
            client = chat_model(ctx, self.role)
            with tracing_context(enabled=False):
                result = client.bind(
                    max_tokens=max_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_model.__name__,
                            "strict": True,
                            "schema": strict_json_schema(schema_model),
                        },
                    },
                ).invoke(
                    [SystemMessage(content=system), HumanMessage(content=user_content)],
                    config={"callbacks": []},
                )
            ctx.check_deadline()
            actual_cost = billed_microusd(result.response_metadata.get("cost"))
            request_id = str(result.response_metadata.get("id") or "")[:100]
            serving_provider = str(
                result.response_metadata.get("provider")
                or client._provider_metadata.get("provider")
                or ""
            )[:100]
            usage = result.usage_metadata or {}
            tokens_in = max(0, int(usage.get("input_tokens", 0)))
            tokens_out = max(0, int(usage.get("output_tokens", 0)))
            served = result.response_metadata.get("model_name") or result.response_metadata.get(
                "model"
            )
            if served not in policy["models"]:
                error = "served_model"
            elif result.additional_kwargs.get("refusal"):
                error = "refusal"
            elif result.response_metadata.get("finish_reason") != "stop":
                error = (
                    "max_tokens"
                    if result.response_metadata.get("finish_reason") == "length"
                    else "invalid_output"
                )
            else:
                parsed = parse_output(result.content, schema_model)
                error = "" if parsed is not None else "invalid_output"
        except Exception:
            error = "unavailable"
        finally:
            if client is not None:
                close_model(client)
            if reservation:
                settle(reservation.pk, actual_cost)
            record_call(
                purpose=purpose,
                model=model,
                prompt_version=prompt_version,
                latency_ms=int((monotonic() - started) * 1000),
                error=error or None,
                agent_run_id=ctx.run_id,
                call_id=call_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                request_id=request_id,
                serving_provider=serving_provider,
            )
        return LLMResult(ok=parsed is not None, data=parsed, error=error or None)
