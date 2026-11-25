"""Short transactions for claims, fencing, completion and delivery; no inference under locks."""

from datetime import timedelta
from time import monotonic

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tchekam.ai.models import AgentDelivery, AgentRun
from tchekam.conversations.models import BotUser, Conversation
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.parser import parse_wasender_payload

from .context import RunContext
from .policy import authorize, enabled_for
from .schemas import AgentDenied


def owned_message(run):
    event = InboundEvent.objects.filter(pk=run.inbound_id).first()
    msg = parse_wasender_payload(event.payload) if event else None
    if (
        msg is None
        or msg.chat_type != "private"
        or msg.sender_phone != run.user.wa_phone.lstrip("+")
        or msg.message_id != run.inbound_key
    ):
        raise AgentDenied("source_unavailable")
    return msg


def queue_turn(ctx) -> bool:
    """Called with Conversation locked by the router. Queue only internal ids."""
    if not enabled_for(ctx.user):
        return False
    event = InboundEvent.objects.filter(message_id=ctx.msg.message_id).first()
    if event is None:
        return False
    if AgentRun.objects.filter(inbound_key=ctx.msg.message_id).exists():
        return True
    pending = AgentRun.objects.filter(user=ctx.user, status__in=["pending", "running"])
    if pending.count() >= settings.AGENT_MAX_PENDING:
        from tchekam.conversations.router import Reply
        from tchekam.i18n import t

        from .render import CATALOGS

        ctx.extra["agent_reply"] = [Reply(t(CATALOGS["unavailable"], ctx.lang))]
        return True
    # Resolve ownership again in the worker. Router message and stored event must agree now too.
    probe = AgentRun(user=ctx.user, inbound=event, inbound_key=ctx.msg.message_id)
    owned_message(probe)
    ctx.conversation.agent_sequence += 1
    run = AgentRun.objects.create(
        user=ctx.user,
        inbound=event,
        inbound_key=ctx.msg.message_id,
        generation=ctx.conversation.agent_generation,
        sequence=ctx.conversation.agent_sequence,
    )
    ctx.enqueue_after("agent.process", run_id=run.pk, queue="agent", lock=f"agent-{ctx.user.pk}")
    return True


def claim(run_id: int) -> RunContext | None:
    probe = AgentRun.objects.filter(pk=run_id).first()
    if probe is None:
        return None
    with transaction.atomic():
        conv = Conversation.objects.select_for_update().get(user_id=probe.user_id)
        run = AgentRun.objects.select_for_update().select_related("user").get(pk=run_id)
        if run.status != "pending":
            return None
        if (
            conv.agent_generation != run.generation
            or conv.flow != Conversation.IDLE
            or not enabled_for(run.user)
        ):
            run.status, run.completed_at = "discarded", timezone.now()
            run.save(update_fields=["status", "completed_at"])
            return None
        earliest = (
            AgentRun.objects.filter(user=run.user, status__in=["pending", "running"])
            .order_by("sequence")
            .first()
        )
        if earliest.pk != run.pk:
            return None
        run.status = "running"
        run.fence += 1
        run.attempts += 1
        run.lease_until = timezone.now() + timedelta(seconds=settings.AGENT_DEADLINE_SECONDS + 10)
        run.save(update_fields=["status", "fence", "attempts", "lease_until"])
        context = RunContext(
            run.pk,
            run.user_id,
            run.generation,
            run.fence,
            run.user.language,
            sequence=run.sequence,
            model_calls=run.model_calls,
            tool_calls=run.tool_calls,
            vision_calls=run.vision_calls,
            stt_calls=run.stt_calls,
        )
        context.deadline = monotonic() + settings.AGENT_DEADLINE_SECONDS
        return context


def invalidate(conv: Conversation) -> None:
    conv.agent_generation += 1
    AgentRun.objects.filter(user_id=conv.user_id, status__in=["pending", "running"]).update(
        status="discarded", completed_at=timezone.now(), outcome="interrupted"
    )
    AgentDelivery.objects.filter(run__user_id=conv.user_id, status="pending").update(
        status="cancelled"
    )


def complete(ctx, state) -> bool:
    from . import memory
    from .render import guard_out

    with transaction.atomic():
        conv = Conversation.objects.select_for_update().get(user_id=ctx.user_id)
        # Match router lock order: conversation, then user, then run.
        user = BotUser.objects.select_for_update().get(pk=ctx.user_id)
        run = AgentRun.objects.select_for_update().get(pk=ctx.run_id)
        authorize(ctx, check_deadline=False)
        replies = state["replies"]
        if ctx.staged:
            if ctx.staged.startswith("lang:"):
                user.language = ctx.staged.partition(":")[2]
                user.save(update_fields=["language"])
                from tchekam.i18n import t

                replies = [t("menu.main", user.language)]
            else:
                # Existing consent/eligibility flow; never submit or ingest an unconfirmed image.
                from tchekam.conversations.router import INTENTS, Context

                msg = owned_message(run)
                from dataclasses import replace

                handoff_ctx = Context(user, conv, replace(msg, kind="text", text="", media=None))
                replies = [r.text for r in INTENTS[ctx.staged](handoff_ctx)]
                # No jobs with inference or media may escape this atomic handoff boundary.
                if handoff_ctx.jobs:
                    raise AgentDenied("handoff_requires_jobs")
                if ctx.staged == "report":
                    run.linked_report_id = conv.state.get("report_id")
            invalidate(conv)
            ctx.generation = conv.agent_generation
            run.generation = ctx.generation
            conv.save()
        guard_out(replies)
        memory.persist(ctx, state.get("text", ""), state["action"])
        run.status, run.outcome, run.completed_at = (
            "complete",
            state.get("outcome", "ok"),
            timezone.now(),
        )
        run.save(update_fields=["generation", "status", "outcome", "completed_at", "linked_report"])
        for index, text in enumerate(replies):
            AgentDelivery.objects.create(run=run, index=index, generation=ctx.generation, text=text)
    return True


def discard(ctx):
    AgentRun.objects.filter(pk=ctx.run_id, fence=ctx.fence, status="running").update(
        status="discarded", outcome="stale", completed_at=timezone.now()
    )


def record_number_shortcut(router_ctx, number):
    from .memory import remember_number

    if not enabled_for(router_ctx.user):
        return
    event = InboundEvent.objects.filter(message_id=router_ctx.msg.message_id).first()
    if event is None:
        return
    conv = router_ctx.conversation
    run = AgentRun.objects.filter(inbound_key=router_ctx.msg.message_id).first()
    if run is None:
        conv.agent_sequence += 1
        run = AgentRun.objects.create(
            user=router_ctx.user,
            inbound=event,
            inbound_key=router_ctx.msg.message_id,
            generation=conv.agent_generation,
            sequence=conv.agent_sequence,
            status="complete",
            outcome="shortcut",
            completed_at=timezone.now(),
        )
    remember_number(
        RunContext(
            run.pk, run.user_id, run.generation, run.fence, router_ctx.lang, sequence=run.sequence
        ),
        number,
    )
