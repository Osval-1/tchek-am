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


class MediaTooLarge(ChannelError):
    pass


MAX_MEDIA_BYTES = 16 * 1024 * 1024


class MessagingChannel(Protocol):
    def send_text(self, to: str, text: str) -> None: ...
    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None: ...
    def send_typing(self, jid: str, ms: int) -> None: ...
    def download_media(self, msg: InboundMessage) -> tuple[bytes, str]: ...
    def leave_group(self, group_jid: str) -> None: ...
    def group_metadata(self, group_jid: str) -> dict[str, Any]: ...


def get_channel() -> MessagingChannel:
    backend = settings.MESSAGING_CHANNEL
    if backend == "fake":
        from .fake import FakeChannel

        return FakeChannel.instance()
    if backend == "wasender":
        return _wasender_channel(settings.WASENDER_API_KEY, settings.WASENDER_BASE_URL)
    raise ValueError(f"Unknown MESSAGING_CHANNEL: {backend!r}")


@lru_cache(maxsize=4)
def _wasender_channel(api_key: str, base_url: str) -> MessagingChannel:
    # One instance per configuration so httpx connection pools are reused across sends.
    from .wasender import WaSenderChannel

    return WaSenderChannel(api_key=api_key, base_url=base_url)
