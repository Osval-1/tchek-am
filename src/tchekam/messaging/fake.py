from typing import Any

from .channel import ChannelError, InboundMessage, refuse_group


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
        self.downloads: list[str] = []  # message ids, in call order
        self.metadata_calls: list[str] = []  # group jids, in call order

    def send_text(self, to: str, text: str, *, allow_group: bool = False) -> None:
        refuse_group(to, allow_group)
        self.sent.append({"type": "text", "to": to, "text": text})

    def send_image(
        self, to: str, image_url: str, caption: str | None = None, *, allow_group: bool = False
    ) -> None:
        refuse_group(to, allow_group)
        self.sent.append({"type": "image", "to": to, "image_url": image_url, "caption": caption})

    def send_typing(self, jid: str, ms: int, *, allow_group: bool = False) -> None:
        refuse_group(jid, allow_group)
        self.sent.append({"type": "typing", "jid": jid, "ms": ms})

    def download_media(self, msg: InboundMessage) -> tuple[bytes, str]:
        self.downloads.append(msg.message_id)
        try:
            return self.media[msg.message_id]
        except KeyError:
            raise ChannelError("no fake media seeded for message") from None

    def leave_group(self, group_jid: str) -> None:
        self.sent.append({"type": "leave_group", "group_jid": group_jid})

    def group_metadata(self, group_jid: str) -> dict[str, Any]:
        self.metadata_calls.append(group_jid)
        return self.groups.get(group_jid, {"subject": "", "participants": []})
