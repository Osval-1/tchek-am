import hashlib
from time import monotonic

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tchekam.ai.models import AgentControl, AgentRun
from tchekam.conversations.models import Conversation

from .context import RunContext
from .schemas import AgentDenied, ModelUnavailable

POLICY_VERSION = "agent-v1"


def enabled_for(user) -> bool:
    if (
        not settings.AGENT_MEMORY_KEYS.get(settings.AGENT_MEMORY_KEY_VERSION)
        or not settings.AGENT_OPERATION_KEY
    ):
        return False
    if not settings.AGENT_ENABLED or user.blocked or user.language not in settings.AGENT_LANGUAGES:
        return False
    control = AgentControl.objects.filter(pk=1, enabled=True).first()
    if control is None or not control.pilot_users.filter(pk=user.pk).exists():
        return False
    bucket = int(hashlib.sha256(f"agent:{user.pk}".encode()).hexdigest()[:8], 16) % 100
    return bucket < min(100, control.rollout_percentage)


def authorize(ctx: RunContext, *, check_deadline: bool = True) -> AgentRun:
    if check_deadline:
        ctx.check_deadline()
    run = AgentRun.objects.select_related("user").get(pk=ctx.run_id)
    conv = Conversation.objects.get(user_id=ctx.user_id)
    if (
        run.user_id != ctx.user_id
        or run.generation != ctx.generation
        or conv.agent_generation != ctx.generation
        or conv.flow != Conversation.IDLE
        or run.fence != ctx.fence
        or run.status != "running"
        or run.lease_until is None
        or run.lease_until <= timezone.now()
        or not enabled_for(run.user)
    ):
        raise AgentDenied("stale")
    return run


def role_policy(role: str) -> dict:
    """Require runnable configuration; privacy is enforced on every request."""
    if role not in ("chat", "vision"):
        raise ModelUnavailable("unsupported_role")
    policy = dict(settings.AGENT_ROLE_POLICIES.get(role, {}))
    selected_model = settings.AGENT_CHAT_MODEL if role == "chat" else settings.AGENT_VISION_MODEL
    policy.setdefault("models", [selected_model])
    if role == "vision" and not AgentControl.objects.filter(pk=1, vision_enabled=True).exists():
        raise ModelUnavailable("vision_disabled")
    if (
        not policy.get("models")
        or not policy.get("endpoints")
        or not settings.OPENROUTER_API_KEY
        or not policy.get("max_cost_microusd", 0) > 0
    ):
        raise ModelUnavailable("role_disabled")
    return policy


def remaining(ctx: RunContext) -> float:
    ctx.check_deadline()
    return max(0.01, min(settings.AGENT_REQUEST_TIMEOUT, ctx.deadline - monotonic()))


def consume(ctx: RunContext, counter: str):
    limits = {
        "model_calls": settings.AGENT_MAX_MODEL_CALLS,
        "tool_calls": settings.AGENT_MAX_TOOL_CALLS,
        "vision_calls": 2,
    }
    if counter not in limits:
        raise AgentDenied("unknown_counter")
    with transaction.atomic():
        Conversation.objects.select_for_update().get(user_id=ctx.user_id)
        authorize(ctx)
        run = AgentRun.objects.select_for_update().get(pk=ctx.run_id)
        count = getattr(run, counter) + 1
        if count > limits[counter]:
            raise AgentDenied("call_limit")
        setattr(run, counter, count)
        run.save(update_fields=[counter])
        setattr(ctx, counter, count)
