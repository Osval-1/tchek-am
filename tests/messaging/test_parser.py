import pytest

from tchekam.messaging.parser import parse_wasender_payload


@pytest.mark.parametrize(
    ("fixture", "message_id", "phone", "text"),
    [
        ("private_text_received", "MSG-PRIV-1", "237670000001", "Hello bot"),
        ("private_text_personal", "MSG-PRIV-2", "237670000002", "Is this number safe?"),
    ],
)
def test_private_text_both_event_names(payload, fixture, message_id, phone, text):
    msg = parse_wasender_payload(payload(fixture))

    assert msg.message_id == message_id
    assert msg.chat_type == "private"
    assert msg.group_jid is None
    assert msg.kind == "text"
    assert msg.text == text
    assert msg.sender_phone == phone
    assert msg.media is None


def test_private_sender_jid_may_be_lid_and_is_not_used_as_phone(payload):
    msg = parse_wasender_payload(payload("private_text_received"))

    assert msg.sender_jid == "123456789012345@lid"
    assert msg.sender_phone == "237670000001"
    assert msg.timestamp == 1633456789
    assert msg.raw_event == "messages.received"


def test_group_text_is_detected(payload):
    msg = parse_wasender_payload(payload("group_text"))

    assert msg.chat_type == "group"
    assert msg.group_jid == "120363000000000001@g.us"
    assert msg.sender_jid == "987654321098765@lid"
    assert msg.sender_phone == "237670000003"
    assert msg.text == "Anyone know this seller?"


def test_group_detected_by_participant_even_with_generic_event(payload):
    data = payload("group_text")
    data["event"] = "messages.received"

    assert parse_wasender_payload(data).chat_type == "group"


def test_image_with_caption(payload):
    msg = parse_wasender_payload(payload("image_caption"))

    assert msg.kind == "image"
    assert msg.text == "Look at this receipt"
    assert msg.media["type"] == "imageMessage"
    assert msg.media["mimetype"] == "image/jpeg"
    assert msg.media["mediaKey"] == "bWVkaWFrZXk="


def test_audio(payload):
    msg = parse_wasender_payload(payload("audio"))

    assert msg.kind == "audio"
    assert msg.text is None
    assert msg.media["type"] == "audioMessage"


def test_from_me_is_ignored(payload):
    assert parse_wasender_payload(payload("from_me_upsert")) is None


def test_flat_data_envelope(payload):
    msg = parse_wasender_payload(payload("flat_data_envelope"))

    assert msg.message_id == "MSG-FLAT-1"
    assert msg.kind == "text"
    assert msg.text == "Flat envelope text"
    assert msg.sender_phone == "237670000006"
    assert msg.timestamp == 1633456795


def test_contact_card_exposes_vcard_as_text(payload):
    msg = parse_wasender_payload(payload("contact_card"))

    assert msg.kind == "contact"
    assert "237690000000" in msg.text


def test_contacts_array_joins_vcards(payload):
    data = payload("contact_card")
    card = data["data"]["messages"]["message"].pop("contactMessage")
    data["data"]["messages"]["message"]["contactsArrayMessage"] = {
        "contacts": [card, {"vcard": "BEGIN:VCARD\nTEL:+237655555555\nEND:VCARD"}]
    }

    msg = parse_wasender_payload(data)

    assert msg.kind == "contact"
    assert "237690000000" in msg.text and "+237655555555" in msg.text


def test_unknown_message_type_is_other(payload):
    data = payload("private_text_received")
    data["data"]["messages"]["message"] = {"locationMessage": {"degreesLatitude": 4.05}}
    data["data"]["messages"].pop("messageBody")

    msg = parse_wasender_payload(data)

    assert msg.kind == "other"
    assert msg.text is None


def test_sender_phone_falls_back_to_pn_jid(payload):
    data = payload("private_text_personal")
    del data["data"]["messages"]["key"]["cleanedSenderPn"]

    assert parse_wasender_payload(data).sender_phone == "237670000002"


def test_sender_phone_none_when_only_lid(payload):
    data = payload("private_text_received")
    del data["data"]["messages"]["key"]["cleanedSenderPn"]

    assert parse_wasender_payload(data).sender_phone is None


@pytest.mark.parametrize(
    "garbage",
    [
        {},
        {"event": "messages.received"},
        {"event": "messages.received", "data": None},
        {"event": "messages.received", "data": {"messages": []}},
        {"event": "messages.received", "data": {"messages": {"key": {"fromMe": False}}}},
        {"event": "session.status", "data": {"status": "connected"}},
        {"event": "messages.received", "data": {"messages": {"key": "nope"}}},
        [],
        "string",
    ],
)
def test_malformed_payloads_return_none(garbage):
    assert parse_wasender_payload(garbage) is None


def test_messages_list_takes_first(payload):
    data = payload("private_text_received")
    data["data"]["messages"] = [data["data"]["messages"]]

    assert parse_wasender_payload(data).message_id == "MSG-PRIV-1"


def test_media_type_key_wins_over_descriptor_field(payload):
    data = payload("image_caption")
    data["data"]["messages"]["message"]["imageMessage"]["type"] = "spoofed"

    assert parse_wasender_payload(data).media["type"] == "imageMessage"


def test_inbound_text_is_cut_to_the_hard_maximum(payload):
    raw = payload("private_text_received")
    raw["data"]["messages"]["messageBody"] = "a" * 9000
    raw["data"]["messages"]["message"] = {"conversation": "a" * 9000}

    msg = parse_wasender_payload(raw)

    assert msg.text == "a" * 4000
