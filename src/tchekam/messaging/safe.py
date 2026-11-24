"""SafeChannel: the safeguards every real send goes through (ISSUES.md Issue 23, ADR-021).

Order inside a send: group refusal, reply-only window, rate limits, typing indicator, send.
Waiting for rate limits is never done here: `Deferred` goes to the caller (`messaging.outbox`),
which re-enqueues the send. The only sleep is the short typing delay, inside a worker task.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from . import limiter
from .channel import (
    ChannelError,
    InboundMessage,
    MessagingChannel,
    RateLimited,
    UnsolicitedMessageBlocked,
    refuse_group,
)

TYPING_MS_PER_CHAR = 40
TYPING_MAX_MS = 4000

_unsolicited_ok: ContextVar[frozenset[str]] = ContextVar("unsolicited_ok", default=frozenset())


def _sleep(seconds: float) -> None:
    time.sleep(seconds)  # a module-level seam so tests never really wait


def typing_delay_ms(text: str) -> int:
    return min(TYPING_MAX_MS, TYPING_MS_PER_CHAR * len(text))


@contextmanager
def allow_unsolicited(to: str) -> Iterator[None]:
    """Let sends to `to` skip the reply window (e.g. delivering a queued PendingNotification)."""
    token = _unsolicited_ok.set(_unsolicited_ok.get() | {to})
    try:
        yield
    finally:
        _unsolicited_ok.reset(token)


def _window_open(to: str) -> bool:
    # Imported here: conversations depends on messaging, not the other way round.
    from tchekam.conversations.models import BotUser

    last = (
        BotUser.objects.filter(wa_phone=f"+{to.lstrip('+')}")
        .values_list("last_inbound_at", flat=True)
        .first()
    )
    return last is not None and timezone.now() - last <= timedelta(
        hours=settings.REPLY_WINDOW_HOURS
    )


class SafeChannel:
    def __init__(self, inner: MessagingChannel) -> None:
        self._inner = inner

    def _admit(self, to: str, allow_group: bool) -> None:
        refuse_group(to, allow_group)  # first: a group send is a bug, never a deferral
        if to not in _unsolicited_ok.get() and not _window_open(to):
            raise UnsolicitedMessageBlocked("recipient has no inbound message in the reply window")
        limiter.acquire(to)

    def send_text(self, to: str, text: str, *, allow_group: bool = False) -> None:
        self._admit(to, allow_group)
        delay = typing_delay_ms(text)
        try:
            self._inner.send_typing(to, delay, allow_group=allow_group)
        except RateLimited:
            raise
        except ChannelError:
            pass  # the indicator is cosmetic; the message itself still goes out
        _sleep(delay / 1000)
        self._inner.send_text(to, text, allow_group=allow_group)

    def send_image(
        self, to: str, image_url: str, caption: str | None = None, *, allow_group: bool = False
    ) -> None:
        self._admit(to, allow_group)
        self._inner.send_image(to, image_url, caption, allow_group=allow_group)

    def send_typing(self, jid: str, ms: int, *, allow_group: bool = False) -> None:
        self._inner.send_typing(jid, ms, allow_group=allow_group)

    def download_media(self, msg: InboundMessage) -> tuple[bytes, str]:
        return self._inner.download_media(msg)

    def leave_group(self, group_jid: str) -> None:
        self._inner.leave_group(group_jid)

    def group_metadata(self, group_jid: str) -> dict[str, Any]:
        return self._inner.group_metadata(group_jid)
