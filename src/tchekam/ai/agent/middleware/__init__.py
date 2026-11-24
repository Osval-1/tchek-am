from time import monotonic
from uuid import uuid4

from django.conf import settings
from langchain.agents.middleware import AgentMiddleware, hook_config

from tchekam.ai.client import record_call

from ..budget import billed_microusd, reserve, settle
from ..policy import authorize, consume, role_policy
from ..schemas import AgentDenied, ResponseAction


class EnforcementMiddleware(AgentMiddleware):
    """Mandatory on every model/tool iteration, including repeated tool batches."""

    def __init__(self, ctx, *, authorize_fn=authorize, consume_fn=consume, audit_fn=record_call):
        self.ctx = ctx
        self.authorize = authorize_fn
        self.consume = consume_fn
        self.audit = audit_fn

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        self.authorize(self.ctx)
        if self.ctx.staged:
            return {"jump_to": "end"}
        size = sum(len(str(m.content).encode()) for m in state["messages"])
        if size > settings.AGENT_CONTEXT_BYTES:
            raise AgentDenied("context_limit")
        return None

    def wrap_model_call(self, request, handler):
        ctx = self.ctx
        self.authorize(ctx)
        self.consume(ctx, "model_calls")
        reservation = None
        call_id = uuid4().hex
        if ctx.model is None:
            policy = role_policy("chat")
            reservation = reserve(ctx, call_id, policy["max_cost_microusd"])
        started, outcome = monotonic(), "model_error"
        tokens_in, tokens_out = 0, 0
        actual_cost = None
        request_id, serving_provider = "", ""
        client = None
        try:
            if ctx.model is None:
                from ..models import chat_model

                client = chat_model(ctx)
                request = request.override(model=client)
            response = handler(request)
            ctx.check_deadline()
            for message in response.result:
                metadata = message.response_metadata
                request_id = str(metadata.get("id") or "")[:100]
                serving_provider = str(
                    metadata.get("provider")
                    or (client._provider_metadata.get("provider") if client else "")
                    or ""
                )[:100]
                actual_cost = billed_microusd(metadata.get("cost"))
                usage = message.usage_metadata or {}
                tokens_in += max(0, int(usage.get("input_tokens", 0)))
                tokens_out += max(0, int(usage.get("output_tokens", 0)))
                if metadata.get("finish_reason") in ("length", "content_filter"):
                    raise AgentDenied("invalid_output")
                if message.additional_kwargs.get("refusal"):
                    raise AgentDenied("refusal")
                if not message.tool_calls:
                    ResponseAction.model_validate_json(message.content)
                if ctx.model is None:
                    served = metadata.get("model_name") or metadata.get("model")
                    if served not in role_policy("chat")["models"]:
                        raise AgentDenied("served_model")
            outcome = "ok"
            return response
        except AgentDenied as exc:
            outcome = (
                exc.args[0]
                if exc.args
                and exc.args[0] in {"invalid_output", "refusal", "served_model", "deadline"}
                else "model_error"
            )
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            outcome = f"provider_http_{status}" if type(status) is int else type(exc).__name__
            raise
        finally:
            if ctx.tracer:
                ctx.tracer.observe(
                    "model_call",
                    outcome="ok" if outcome == "ok" else "error",
                    latency_ms=int((monotonic() - started) * 1000),
                    model_calls=ctx.model_calls,
                    tool_calls=ctx.tool_calls,
                )
            if client is not None:
                from ..models import close_model

                close_model(client)
            # Unknown pricing/usage keeps the full conservative charge. Never refund on timeout.
            if reservation:
                settle(reservation.pk, actual_cost)
            self.audit(
                purpose="agent.chat",
                model="fake" if ctx.model else policy["models"][0],
                prompt_version="agent-v1",
                latency_ms=int((monotonic() - started) * 1000),
                error=None if outcome == "ok" else outcome,
                agent_run_id=ctx.run_id,
                call_id=call_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                request_id=request_id,
                serving_provider=serving_provider,
            )

    def wrap_tool_call(self, request, handler):
        # create_agent may dispatch a tool batch on worker threads. Serialize authority and
        # staged transitions even when a compromised model requests parallel tools.
        from django.db import close_old_connections, connections

        with self.ctx.tool_lock:
            close_old_connections()
            started, outcome = monotonic(), "error"
            try:
                self.authorize(self.ctx)
                result = handler(request)
                outcome = "ok"
                return result
            finally:
                if self.ctx.tracer:
                    self.ctx.tracer.observe(
                        request.tool_call["name"],
                        outcome=outcome,
                        latency_ms=int((monotonic() - started) * 1000),
                        model_calls=self.ctx.model_calls,
                        tool_calls=self.ctx.tool_calls,
                    )
                connections.close_all()
