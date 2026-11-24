from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from tchekam.ai.models import AgentDelivery, AgentRun
from tchekam.conversations.models import Conversation
from tchekam.core.tasks import enqueue, register
from tchekam.messaging.channel import (
    ChannelError,
    RateLimited,
    UnsolicitedMessageBlocked,
    get_channel,
)
from tchekam.messaging.outbox import lock_for

from .execution import claim
from .graph import build_graph
from .policy import enabled_for


def schedule_deliveries(run_id):
    for delivery in AgentDelivery.objects.filter(run_id=run_id, status="pending"):
        enqueue(
            "agent.deliver",
            delivery_id=delivery.pk,
            queue="whatsapp",
            lock=lock_for(str(delivery.run.user_id)),
        )


@register("agent.process")
def process(run_id: int):
    ctx = claim(run_id)
    if ctx is None:
        return
    build_graph(ctx).invoke({"run_id": run_id}, config={"recursion_limit": 50, "callbacks": []})
    following = (
        AgentRun.objects.filter(user_id=ctx.user_id, status="pending").order_by("sequence").first()
    )
    if following:
        enqueue("agent.process", run_id=following.pk, queue="agent", lock=f"agent-{ctx.user_id}")


@register("agent.deliver")
def deliver(delivery_id: int):
    probe = AgentDelivery.objects.filter(pk=delivery_id).select_related("run").first()
    if probe is None:
        return
    now = timezone.now()
    with transaction.atomic():
        conv = Conversation.objects.select_for_update().get(user_id=probe.run.user_id)
        row = (
            AgentDelivery.objects.select_for_update()
            .select_related("run__user")
            .get(pk=delivery_id)
        )
        if row.status != "pending" or row.lease_until and row.lease_until > now:
            return
        if (
            not enabled_for(row.run.user)
            or conv.agent_generation != row.generation
            or row.attempts >= 20
        ):
            row.status = "cancelled"
            row.save(update_fields=["status"])
            return
        # Do not send a later reply/turn while an earlier one remains pending.
        earlier = (
            AgentDelivery.objects.filter(run__user_id=row.run.user_id, status="pending")
            .filter(run__sequence__lt=row.run.sequence)
            .exists()
        )
        if (
            earlier
            or AgentDelivery.objects.filter(
                run=row.run, status="pending", index__lt=row.index
            ).exists()
        ):
            return  # reconciler reschedules; no content ever enters queue arguments
        row.attempts += 1
        row.lease_until = now + timedelta(seconds=60)
        row.save(update_fields=["attempts", "lease_until"])
        text, to = row.text, row.run.user.wa_phone.lstrip("+")
    # Channel guards enforce reply windows and rate limits. Re-read right before transport.
    row.refresh_from_db()
    row.run.user.refresh_from_db()
    conv.refresh_from_db()
    if (
        row.status != "pending"
        or not enabled_for(row.run.user)
        or conv.agent_generation != row.generation
    ):
        AgentDelivery.objects.filter(pk=delivery_id).update(status="cancelled", lease_until=None)
        return
    try:
        get_channel().send_text(to, text)
    except UnsolicitedMessageBlocked:
        AgentDelivery.objects.filter(pk=delivery_id).update(status="cancelled", lease_until=None)
    except ChannelError as exc:
        delay = exc.retry_after if isinstance(exc, RateLimited) else 30
        AgentDelivery.objects.filter(pk=delivery_id).update(lease_until=None)
        enqueue(
            "agent.deliver",
            delivery_id=delivery_id,
            queue="whatsapp",
            lock=lock_for(to),
            schedule_in_seconds=max(1, delay),
        )
    else:
        AgentDelivery.objects.filter(pk=delivery_id).update(status="sent", lease_until=None)


@register("agent.reconcile", cron="* * * * *")
def reconcile(timestamp: int = 0):
    now = timezone.now()
    expired = AgentRun.objects.filter(status="running", lease_until__lte=now)
    for probe in expired:
        with transaction.atomic():
            Conversation.objects.select_for_update().get(user_id=probe.user_id)
            run = AgentRun.objects.select_for_update().get(pk=probe.pk)
            if run.status != "running" or run.lease_until > now:
                continue
            run.fence += 1
            run.status = "pending"
            if run.attempts >= 3:
                run.outcome = "recovery_exhausted"
            run.save(update_fields=["status", "fence", "outcome"])
    # Committed-but-unscheduled turns and delivery gaps, as well as abandoned leases.
    for run in AgentRun.objects.filter(status="pending").order_by("user_id", "sequence")[:200]:
        enqueue("agent.process", run_id=run.pk, queue="agent", lock=f"agent-{run.user_id}")
    for row in AgentDelivery.objects.filter(status="pending", lease_until__lte=now):
        row.lease_until = None
        row.save(update_fields=["lease_until"])
    for run_id in (
        AgentDelivery.objects.filter(status="pending", lease_until=None)
        .values_list("run_id", flat=True)
        .distinct()[:200]
    ):
        schedule_deliveries(run_id)
