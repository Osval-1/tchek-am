"""Deliver replies, and re-enqueue only what was not sent when the channel pushes back.

Routing has already committed by the time replies go out, so a failed send must never re-run
`process_inbound` (it would route the message twice). Instead the unsent tail of the replies
becomes a `messaging.deliver_replies` job on the `whatsapp` queue, delayed by the provider's
`retry_after` (or our own limiter's). Delivery is at-least-once: a crash between the provider
accepting a message and the job finishing can send it again.
"""

import hashlib
import logging
from typing import Any

from tchekam.core.tasks import enqueue

from .channel import (
    ChannelError,
    MessagingChannel,
    RateLimited,
    UnsolicitedMessageBlocked,
    get_channel,
)

logger = logging.getLogger(__name__)

QUEUE = "whatsapp"
LOCKS = 3  # at most this many sends run at once (one Procrastinate lock each)
MAX_ATTEMPTS = 3  # generic channel errors
MAX_DEFERRALS = 20  # rate limits are the provider's or ours, not a fault: allow many more
BACKOFF_SECONDS = 30

Item = dict[str, Any]  # {"text": str | None, "image_url": str | None}, JSON-safe for the queue


class DeliveryIncomplete(ChannelError):
    """Replies did not all go out on the first try; callers must not mark them as delivered."""


def lock_for(recipient: str) -> str:
    """Stable per-recipient lock name: sends to one person stay ordered, three run in parallel."""
    # Not hash(): that is randomised per process and workers must agree.
    digest = int.from_bytes(hashlib.sha256(recipient.encode()).digest()[:4], "big")
    return f"{QUEUE}-{digest % LOCKS}"


def schedule(
    to: str, items: list[Item], *, delay: int, attempt: int = 0, deferrals: int = 0
) -> None:
    enqueue(
        "messaging.deliver_replies",
        schedule_in_seconds=delay,
        queue=QUEUE,
        lock=lock_for(to),
        to=to,
        items=items,
        attempt=attempt,
        deferrals=deferrals,
    )


def _send(channel: MessagingChannel, to: str, item: Item) -> None:
    if item.get("image_url"):
        channel.send_image(to, item["image_url"], caption=item.get("text"))
    elif item.get("text"):
        channel.send_text(to, item["text"])


SENT, DEFERRED, RETRYING, ABANDONED = "sent", "deferred", "retrying", "abandoned"


def deliver(to: str, items: list[Item], *, attempt: int = 0, deferrals: int = 0) -> str:
    """Send `items` in order and say how it went: SENT, DEFERRED (a rate limit; the rest is
    queued for later), RETRYING (a transient error; the rest is queued with backoff) or
    ABANDONED (blocked, or retries ran out)."""
    channel = get_channel()
    for index, item in enumerate(items):
        rest = items[index:]
        try:
            _send(channel, to, item)
        except RateLimited as exc:
            if deferrals >= MAX_DEFERRALS:
                logger.warning(
                    "outbox: gave up after %s deferrals: %s", deferrals, type(exc).__name__
                )
                return ABANDONED
            schedule(to, rest, delay=exc.retry_after, attempt=attempt, deferrals=deferrals + 1)
            return DEFERRED
        except UnsolicitedMessageBlocked:
            logger.warning("outbox: dropped %s message(s), outside the reply window", len(rest))
            return ABANDONED
        except ChannelError as exc:
            # Class name only: provider errors can echo bodies or numbers.
            if attempt + 1 >= MAX_ATTEMPTS:
                logger.warning(
                    "outbox: gave up on %s message(s): %s", len(rest), type(exc).__name__
                )
                return ABANDONED
            schedule(
                to,
                rest,
                delay=BACKOFF_SECONDS * 2**attempt,
                attempt=attempt + 1,
                deferrals=deferrals,
            )
            return RETRYING
    return SENT
