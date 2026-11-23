import pytest

from tchekam.messaging.channel import get_channel
from tchekam.messaging.fake import FakeChannel
from tchekam.messaging.parser import parse_wasender_payload


def test_fake_is_default_in_tests_and_a_singleton():
    assert get_channel() is FakeChannel.instance()
    assert get_channel() is get_channel()


def test_wasender_selected_by_setting(settings):
    settings.MESSAGING_CHANNEL = "wasender"
    settings.WASENDER_API_KEY = "k"

    channel = get_channel()

    assert type(channel).__name__ == "WaSenderChannel"


def test_unknown_channel_raises(settings):
    settings.MESSAGING_CHANNEL = "carrier-pigeon"

    with pytest.raises(ValueError):
        get_channel()


def test_fake_channel_records(fake_channel, payload):
    fake_channel.send_text("2376", "a")
    fake_channel.send_image("2376", "https://x", caption="c")
    fake_channel.send_typing("j", 100)
    fake_channel.leave_group("g@g.us")

    assert [s["type"] for s in fake_channel.sent] == ["text", "image", "typing", "leave_group"]
    assert fake_channel.sent[0] == {"type": "text", "to": "2376", "text": "a"}


def test_fake_channel_serves_seeded_media_and_metadata(fake_channel, payload):
    fake_channel.media["MSG-IMG-1"] = (b"img", "image/png")
    fake_channel.groups["g@g.us"] = {"subject": "Market"}
    msg = parse_wasender_payload(payload("image_caption"))

    assert fake_channel.download_media(msg) == (b"img", "image/png")
    assert fake_channel.group_metadata("g@g.us") == {"subject": "Market"}


def test_wasender_channel_is_reused_per_settings(settings):
    settings.MESSAGING_CHANNEL = "wasender"
    settings.WASENDER_API_KEY = "k1"
    first = get_channel()

    assert get_channel() is first

    settings.WASENDER_API_KEY = "k2"
    assert get_channel() is not first
