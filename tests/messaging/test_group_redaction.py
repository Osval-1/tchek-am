"""Group payloads are stored without any message text (ADR-012): redacted before saving."""

import json

import pytest

from tchekam.messaging import hooks
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.parser import parse_wasender_payload, storable_payload

from .test_webhook import post

SECRETS = ("SECRET", "Anyone know this seller", "iPhone", "Seller Display Name")


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _has_key(value, name: str) -> bool:
    if isinstance(value, dict):
        return name in value or any(_has_key(v, name) for v in value.values())
    if isinstance(value, list):
        return any(_has_key(v, name) for v in value)
    return False


@pytest.fixture(autouse=True)
def _no_group_handling(monkeypatch):
    # Storage is what is under test here; group processing has its own tests.
    monkeypatch.setattr(hooks, "on_group_message", lambda msg: None)


@pytest.mark.django_db
@pytest.mark.parametrize("fixture", ["group_text", "group_image_caption"])
def test_stored_group_payload_has_no_text(
    client, payload, fake_channel, django_capture_on_commit_callbacks, fixture
):
    with django_capture_on_commit_callbacks(execute=True):
        assert post(client, payload(fixture)).status_code == 200

    stored = InboundEvent.objects.get().payload
    assert not _has_key(stored, "messageBody")
    assert not _has_key(stored, "caption")
    assert not _has_key(stored, "conversation")
    assert not _has_key(stored, "pushName")
    assert not _has_key(stored, "jpegThumbnail")
    assert not _has_key(stored, "contextInfo")
    for secret in SECRETS:
        assert secret not in _dump(stored)


@pytest.mark.django_db
def test_flat_envelope_group_payload_is_redacted_too(
    client, payload, fake_channel, django_capture_on_commit_callbacks
):
    body = payload("group_image_caption")
    body["data"] = body["data"]["messages"]  # the "data.key" variant from the provider docs

    with django_capture_on_commit_callbacks(execute=True):
        post(client, body)

    stored = InboundEvent.objects.get().payload
    for secret in SECRETS:
        assert secret not in _dump(stored)


@pytest.mark.parametrize(
    "text_field",
    [
        {"extendedTextMessage": {"text": "SECRET-EXT"}},
        {"conversation": "SECRET-CONV"},
        {"audioMessage": {"url": "https://x", "caption": "SECRET-AUDIO"}},
        {"videoMessage": {"url": "https://x", "caption": "SECRET-VIDEO"}},
        {"contactMessage": {"vcard": "BEGIN:VCARD SECRET-VCARD"}},
    ],
)
def test_every_non_image_group_message_keeps_no_content(payload, text_field):
    body = payload("group_text")
    body["data"]["messages"]["message"] = text_field
    msg = parse_wasender_payload(body)

    stored = storable_payload(body, msg)

    assert "SECRET" not in _dump(stored)
    assert stored["data"]["messages"]["message"] == {}


def test_redacted_image_payload_still_parses_for_the_download_job(payload):
    body = payload("group_image_caption")
    original = parse_wasender_payload(body)

    again = parse_wasender_payload(storable_payload(body, original))

    assert again.message_id == original.message_id == "MSG-GRP-IMG-1"
    assert again.chat_type == "group"
    assert again.group_jid == "120363000000000001@g.us"
    assert again.sender_phone == "237670000003"
    assert again.kind == "image"
    assert again.text is None
    assert again.raw_event == "messages-group.received"
    # Exactly what decrypt-media needs, nothing that carries text or pixels.
    assert again.media == {
        "type": "imageMessage",
        "url": "https://mmg.whatsapp.net/o1/v/t62/abc",
        "mimetype": "image/jpeg",
        "fileSha256": "c2hhMjU2",
        "fileLength": "12345",
        "mediaKey": "bWVkaWFLZXk=",
        "fileEncSha256": "ZW5jU2hh",
        "directPath": "/o1/v/t62/abc",
        "mediaKeyTimestamp": "1633456790",
    }


def test_private_payloads_are_stored_unchanged(payload):
    body = payload("image_caption")

    assert storable_payload(body, parse_wasender_payload(body)) is body


def test_non_string_media_fields_are_dropped(payload):
    body = payload("group_image_caption")
    body["data"]["messages"]["message"]["imageMessage"]["url"] = {"nested": "SECRET-NESTED"}

    stored = storable_payload(body, parse_wasender_payload(body))

    assert "SECRET" not in _dump(stored)


@pytest.mark.django_db
def test_group_text_never_reaches_the_logs(
    client, payload, fake_channel, caplog, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        post(client, payload("group_image_caption"))
        post(client, payload("group_text"))

    for secret in SECRETS:
        assert secret not in caplog.text
