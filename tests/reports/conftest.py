"""A scripted WhatsApp user for end-to-end report flow tests (webhook pipeline, all fakes)."""

import io
import json
from itertools import count

import pytest
from PIL import Image

from tchekam.conversations.models import BotUser, Conversation
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.tasks import process_inbound

SENDER = "237670000055"
_ids = count(1)


def png(color: str = "red", size: int = 24) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (size, size), color).save(out, format="PNG")
    return out.getvalue()


def extraction_json(**overrides) -> str:
    data = {
        "phone_numbers": ["677123456"],
        "account_names": [{"name": "Jean Dupont", "provider": "momo"}],
        "amounts_xaf": [25000],
        "transaction_ids": [],
        "dates": ["2026-11-20"],
        "operator": "mtn",
        "product": "phone",
        "scam_type": "fake_product",
        "summary": "The buyer paid for a phone that was never delivered.",
        "evidence_kinds": ["chat", "momo_sms"],
        "tamper_observations": [],
        "payment_proof_candidate": True,
    }
    data.update(overrides)
    return json.dumps(data)


class Bot:
    """Sends messages as one user through process_inbound; each call returns the texts sent."""

    def __init__(self, channel, user):
        self.channel = channel
        self.user = user
        self.last_id = ""

    def _deliver(self, message: dict, body: str | None = None, mid: str | None = None):
        self.last_id = mid or f"RPT-{next(_ids)}"
        envelope = {
            "key": {
                "id": self.last_id,
                "fromMe": False,
                "remoteJid": f"{SENDER}@s.whatsapp.net",
                "cleanedSenderPn": SENDER,
            },
            "message": message,
            "messageTimestamp": 1633456789,
        }
        if body is not None:
            envelope["messageBody"] = body
        payload = {"event": "messages.received", "timestamp": 1, "data": {"messages": envelope}}
        event = InboundEvent.objects.create(
            message_id=self.last_id, event=payload["event"], payload=payload
        )
        self.channel.sent.clear()
        process_inbound(event_id=event.pk)
        return [m.get("text") or m.get("caption") or "" for m in self.channel.sent]

    def text(self, text: str) -> list[str]:
        return self._deliver({"conversation": text}, body=text)

    def image(self, data: bytes | None = None, mimetype: str = "image/png", seed=True):
        mid = f"RPT-{next(_ids)}"
        if seed:
            self.channel.media[mid] = (data or png(), mimetype)
        return self._deliver({"imageMessage": {"mimetype": mimetype, "url": "https://x"}}, mid=mid)

    def audio(self, data: bytes = b"OggS-voice", mimetype: str = "audio/ogg", seed=True):
        mid = f"RPT-{next(_ids)}"
        if seed:
            self.channel.media[mid] = (data, mimetype)
        return self._deliver({"audioMessage": {"mimetype": mimetype, "url": "https://x"}}, mid=mid)

    def video(self) -> list[str]:
        return self._deliver({"videoMessage": {"mimetype": "video/mp4", "url": "https://x"}})

    @property
    def conversation(self) -> Conversation:
        return Conversation.objects.get(user=self.user)


@pytest.fixture
def bot(fake_channel, fake_llm, fake_speech, object_store):
    user = BotUser.objects.create(wa_phone=f"+{SENDER}", language="en")
    Conversation.objects.create(user=user)
    return Bot(fake_channel, user)
