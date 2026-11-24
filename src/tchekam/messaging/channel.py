"""The messaging boundary: everything outside this app talks to WhatsApp through here."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, Protocol

from django.conf import settings

ChatType = Literal["private", "group"]
Kind = Literal["text", "image", "audio", "contact", "other"]


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    sender_phone: str | None  # digits only; None when the provider only gave us a LID
    sender_jid: str | None
    chat_type: ChatType
    group_jid: str | None  # None for private chats
    kind: Kind
    text: str | None  # message text, media caption, or vCard text for contact cards
    media: dict[str, Any] | None  # {"type": "imageMessage", ...provider descriptor fields}
    timestamp: int | None
    raw_event: str


class ChannelError(Exception):
    """A messaging provider call failed. Messages never contain bodies or phone numbers."""


class RateLimited(ChannelError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited; retry after {retry_after}s")
        self.retry_after = retry_after


class Deferred(RateLimited):
    """Our own limiter says wait. A RateLimited, so callers treat it like the provider's."""


class UnsolicitedMessageBlocked(ChannelError):
    """The recipient has not written to us within the reply window (ADR-011)."""


class MediaTooLarge(ChannelError):
    pass


MAX_MEDIA_BYTES = 16 * 1024 * 1024
GROUP_JID_SUFFIX = "@g.us"


class GroupSendForbidden(ValueError):
    """A send was aimed at a group JID. The bot never posts in groups (ADR-012).

    Deliberately not a ChannelError: callers that swallow provider failures must not hide this.
    """


def is_group_jid(to: str) -> bool:
    return to.strip().lower().endswith(GROUP_JID_SUFFIX)


def refuse_group(to: str, allow_group: bool) -> None:
    """Every send_* implementation calls this first. `allow_group` is unused in the MVP."""
    if not allow_group and is_group_jid(to):
        raise GroupSendForbidden("refusing to send to a group")


class MessagingChannel(Protocol):
    # Every send_* raises GroupSendForbidden for a group JID unless allow_group=True.
    def send_text(self, to: str, text: str, *, allow_group: bool = False) -> None: ...
    def send_image(
        self, to: str, image_url: str, caption: str | None = None, *, allow_group: bool = False
    ) -> None: ...
    def send_typing(self, jid: str, ms: int, *, allow_group: bool = False) -> None: ...
    def download_media(self, msg: InboundMessage) -> tuple[bytes, str]: ...
    def leave_group(self, group_jid: str) -> None: ...
    def group_metadata(self, group_jid: str) -> dict[str, Any]: ...


def get_channel() -> MessagingChannel:
    channel = _base_channel()
    if not settings.CHANNEL_SAFEGUARDS:
        return channel
    from .safe import SafeChannel

    return SafeChannel(channel)


def _active_wasender_key() -> str:
    if not settings.WASENDER_BACKUP_API_KEY:
        return settings.WASENDER_API_KEY  # no backup configured: skip the database read
    from .models import ChannelState

    if ChannelState.current() == "backup":
        return settings.WASENDER_BACKUP_API_KEY
    return settings.WASENDER_API_KEY


def _base_channel() -> MessagingChannel:
    backend = settings.MESSAGING_CHANNEL
    if backend == "fake":
        from .fake import FakeChannel

        return FakeChannel.instance()
    if backend == "wasender":
        # Keyed by API key below, so a failover switch takes effect on the next call.
        return _wasender_channel(_active_wasender_key(), settings.WASENDER_BASE_URL)
    raise ValueError(f"Unknown MESSAGING_CHANNEL: {backend!r}")


@lru_cache(maxsize=4)
def _wasender_channel(api_key: str, base_url: str) -> MessagingChannel:
    # One instance per configuration so httpx connection pools are reused across sends.
    from .wasender import WaSenderChannel

    return WaSenderChannel(api_key=api_key, base_url=base_url)
