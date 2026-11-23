from typing import Any

from .channel import ChannelError, InboundMessage


class FakeChannel:
    """In-memory channel for tests and local runs: records sends, serves seeded media."""

    _instance: "FakeChannel | None" = None

    def __init__(self) -> None:
        self.reset()

    @classmethod
    def instance(cls) -> "FakeChannel":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reset(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.media: dict[str, tuple[bytes, str]] = {}  # message_id -> (bytes, mimetype)
        self.groups: dict[str, dict[str, Any]] = {}  # group_jid -> metadata

    def send_text(self, to: str, text: str) -> None:
        self.sent.append({"type": "text", "to": to, "text": text})

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None:
        self.sent.append({"type": "image", "to": to, "image_url": image_url, "caption": caption})

    def send_typing(self, jid: str, ms: int) -> None:
        self.sent.append({"type": "typing", "jid": jid, "ms": ms})

    def download_media(self, msg: InboundMessage) -> tuple[bytes, str]:
        try:
            return self.media[msg.message_id]
        except KeyError:
            raise ChannelError("no fake media seeded for message") from None

    def leave_group(self, group_jid: str) -> None:
        self.sent.append({"type": "leave_group", "group_jid": group_jid})

    def group_metadata(self, group_jid: str) -> dict[str, Any]:
        return self.groups.get(group_jid, {"subject": "", "participants": []})
