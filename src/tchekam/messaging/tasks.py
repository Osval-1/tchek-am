"""Inbound processing with at-least-once semantics.

An event is claimed atomically (RECEIVED -> PROCESSING), so two workers never handle it at
once. A crash after replies went out but before PROCESSED can resend them: the recovery job
resets claims older than STUCK_AFTER and re-enqueues the event.
"""

import logging
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from tchekam.conversations.router import Reply
from tchekam.conversations.service import handle_private_message
from tchekam.core.tasks import enqueue, register

from . import hooks, outbox
from .channel import InboundMessage, RateLimited
from .models import InboundEvent
from .parser import parse_wasender_payload

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 30
STUCK_AFTER = timedelta(minutes=10)


def _handle(msg: InboundMessage) -> None:
    if msg.chat_type == "group":
        hooks.on_group_message(msg)
        return
    if not msg.sender_phone:
        return
    to = msg.sender_phone

    def deliver(replies: list[Reply]) -> None:
        # Unsent replies are re-queued by the outbox, never by re-running this event.
        items = [{"text": r.text, "image_url": r.image_url} for r in replies]
        if outbox.deliver(to, items) not in (outbox.SENT, outbox.DEFERRED):
            # Stops handle_private_message from marking queued notifications as delivered.
            # A retry may still send the replies, so a notification can arrive twice, never zero.
            raise outbox.DeliveryIncomplete("replies were not delivered")

    # Replies go out first; jobs the handlers queued run after them (see the service).
    handle_private_message(msg, deliver=deliver)


def _requeue(event: InboundEvent, *, delay: int, deferrals: int) -> None:
    msg = parse_wasender_payload(event.payload)
    # Same lock as the webhook's enqueue, so a retry stays ordered with the sender's other work.
    key = (msg.sender_phone or msg.sender_jid or msg.group_jid or "") if msg else ""
    enqueue(
        "messaging.process_inbound",
        schedule_in_seconds=delay,
        queue=outbox.QUEUE,
        lock=outbox.lock_for(key),
        event_id=event.pk,
        deferrals=deferrals,
    )


@register("messaging.process_inbound")
def process_inbound(event_id: int, deferrals: int = 0) -> None:
    claimed = InboundEvent.objects.filter(pk=event_id, status=InboundEvent.Status.RECEIVED).update(
        status=InboundEvent.Status.PROCESSING,
        claimed_at=timezone.now(),
        attempts=F("attempts") + 1,
    )
    if claimed != 1:
        if not InboundEvent.objects.filter(pk=event_id).exists():
            logger.warning("process_inbound: event %s not found", event_id)
        return  # processed already, or another worker holds it
    event = InboundEvent.objects.get(pk=event_id)

    msg = parse_wasender_payload(event.payload)
    if msg is None:
        event.status = InboundEvent.Status.IGNORED
        event.save(update_fields=["status"])
        return

    try:
        _handle(msg)
    except Exception as exc:
        # Class name only: exception text from providers can echo bodies or numbers.
        if getattr(exc, "after_commit", False):
            # Routing is committed: running the event again would route twice.
            _fail(event, exc)
        elif isinstance(exc, RateLimited):
            # Raised before any reply went out (e.g. media download), and routing rolled back, so
            # running the event again is safe. A rate limit is not a fault: it costs no attempt.
            if deferrals >= outbox.MAX_DEFERRALS:
                _fail(event, exc)
            else:
                _reset(event, exc, refund=True)
                _requeue(event, delay=exc.retry_after, deferrals=deferrals + 1)
        elif event.attempts >= MAX_ATTEMPTS:
            _fail(event, exc)
        else:
            _reset(event, exc)
            logger.warning(
                "process_inbound: event %s failed with %s, retrying", event.pk, event.error
            )
            _requeue(event, delay=BACKOFF_SECONDS * 2 ** (event.attempts - 1), deferrals=deferrals)
        return

    event.status = InboundEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "processed_at"])


def _reset(event: InboundEvent, exc: Exception, *, refund: bool = False) -> None:
    event.status = InboundEvent.Status.RECEIVED
    event.claimed_at = None
    event.error = type(exc).__name__
    if refund:
        event.attempts -= 1
    event.save(update_fields=["status", "claimed_at", "error", "attempts"])


def _fail(event: InboundEvent, exc: Exception) -> None:
    event.status = InboundEvent.Status.FAILED
    event.error = type(exc).__name__
    event.save(update_fields=["status", "error"])
    logger.warning("process_inbound: event %s failed with %s", event.pk, event.error)


@register("messaging.deliver_replies")
def deliver_replies(
    to: str, items: list[outbox.Item], attempt: int = 0, deferrals: int = 0
) -> None:
    outbox.deliver(to, items, attempt=attempt, deferrals=deferrals)


@register("messaging.recover_stuck_events", cron="*/5 * * * *")
def recover_stuck_events(timestamp: int | None = None) -> int:
    """Hand back events a crashed worker left in PROCESSING. Returns how many were reset."""
    cutoff = timezone.now() - STUCK_AFTER
    stuck = list(
        InboundEvent.objects.filter(status=InboundEvent.Status.PROCESSING, claimed_at__lt=cutoff)
    )
    recovered = 0
    for event in stuck:
        # Per-row conditional update: a worker that finished meanwhile is left alone.
        stale = InboundEvent.objects.filter(
            pk=event.pk, status=InboundEvent.Status.PROCESSING, claimed_at__lt=cutoff
        )
        if event.attempts >= MAX_ATTEMPTS:
            # Claimed MAX_ATTEMPTS times and never finished: stop looping on a poison event.
            stale.update(status=InboundEvent.Status.FAILED, error="StuckProcessing")
        elif stale.update(status=InboundEvent.Status.RECEIVED, claimed_at=None):
            recovered += 1
            _requeue(event, delay=0, deferrals=0)
    if recovered:
        logger.warning("recover_stuck_events: reset %s event(s)", recovered)
    return recovered
