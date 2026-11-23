"""Turn a WaSender webhook payload into an InboundMessage.

The provider docs contradict themselves (see docs/integrations/wasender.md), so every
lookup here is defensive: wrong types or missing fields mean "not a message", never a crash.
"""

import re
from typing import Any

from .channel import InboundMessage, Kind

MEDIA_KINDS: dict[str, Kind] = {
    "imageMessage": "image",
    "audioMessage": "audio",
    "videoMessage": "other",
    "documentMessage": "other",
    "stickerMessage": "other",
}
_PHONE_JID_SUFFIX = "@s.whatsapp.net"


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _digits(value: Any) -> str | None:
    if not isinstance(value, str | int):
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def _timestamp(*candidates: Any) -> int | None:
    for value in candidates:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _phone_from_jid(jid: str | None) -> str | None:
    # Only "<number>@s.whatsapp.net" encodes a phone number; a "@lid" never does.
    if jid and jid.endswith(_PHONE_JID_SUFFIX):
        return _digits(jid.removesuffix(_PHONE_JID_SUFFIX).split(":")[0])
    return None


def _envelope(payload: dict) -> dict:
    data = _dict(payload.get("data"))
    if "messages" in data:
        messages = data["messages"]
        if isinstance(messages, list):
            messages = messages[0] if messages else None
        return _dict(messages)
    return data


# Hard cap on inbound text, applied here so no handler (story, edits, checks) ever parses an
# unbounded string. The story itself is capped at the same size in reports.flow.
MAX_TEXT_CHARS = 4000


def _content(message: dict, body: str | None) -> tuple[Kind, str | None, dict | None]:
    """Return (kind, text, media) for the WhatsApp `message` object."""
    if "contactMessage" in message or "contactsArrayMessage" in message:
        cards = [_dict(message.get("contactMessage"))]
        cards += [_dict(c) for c in _dict(message.get("contactsArrayMessage")).get("contacts", [])]
        vcards = [v for c in cards if (v := _str(c.get("vcard")))]
        return "contact", "\n".join(vcards) or body, None
    for key, kind in MEDIA_KINDS.items():
        descriptor = message.get(key)
        if isinstance(descriptor, dict):
            caption = body or _str(descriptor.get("caption"))
            return kind, caption, {**descriptor, "type": key}
    text = (
        body
        or _str(message.get("conversation"))
        or _str(_dict(message.get("extendedTextMessage")).get("text"))
    )
    return ("text", text, None) if text else ("other", None, None)


def parse_wasender_payload(payload: Any) -> InboundMessage | None:
    """Return the normalised message, or None for anything we must not act on."""
    if not isinstance(payload, dict):
        return None
    envelope = _envelope(payload)
    key = _dict(envelope.get("key"))
    message_id = _str(key.get("id"))
    if message_id is None or key.get("fromMe") is True:
        return None

    event = _str(payload.get("event")) or ""
    remote_jid = _str(key.get("remoteJid"))
    participant = _str(key.get("participant"))
    is_group = bool(
        participant
        or key.get("cleanedParticipantPn")
        or "group" in event
        or (remote_jid or "").endswith("@g.us")
    )
    if is_group:
        sender_jid = participant
        phone = _digits(key.get("cleanedParticipantPn")) or _phone_from_jid(participant)
    else:
        sender_jid = remote_jid
        phone = _digits(key.get("cleanedSenderPn")) or _phone_from_jid(remote_jid)

    kind, text, media = _content(_dict(envelope.get("message")), _str(envelope.get("messageBody")))
    return InboundMessage(
        message_id=message_id,
        sender_phone=phone,
        sender_jid=sender_jid,
        chat_type="group" if is_group else "private",
        group_jid=remote_jid if is_group else None,
        kind=kind,
        text=text[:MAX_TEXT_CHARS] if text else text,
        media=media,
        timestamp=_timestamp(envelope.get("messageTimestamp"), payload.get("timestamp")),
        raw_event=event,
    )
