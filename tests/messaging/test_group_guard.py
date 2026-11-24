"""The bot never sends anything to a group (ADR-012): every send_* refuses a group JID."""

import httpx
import pytest

from tchekam.messaging.channel import GroupSendForbidden, is_group_jid
from tchekam.messaging.wasender import WaSenderChannel

GROUP = "120363000000000001@g.us"


def _wasender():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"success": True})

    channel = WaSenderChannel(
        api_key="k", base_url="https://wasender.test/api", transport=httpx.MockTransport(handler)
    )
    return channel, requests


SENDS = [
    ("send_text", (GROUP, "hello")),
    ("send_image", (GROUP, "https://x/img.jpg")),
    ("send_typing", (GROUP, 1000)),
]


@pytest.mark.parametrize(("method", "args"), SENDS)
def test_wasender_refuses_every_send_to_a_group(method, args):
    channel, requests = _wasender()

    with pytest.raises(GroupSendForbidden):
        getattr(channel, method)(*args)

    assert requests == []


@pytest.mark.parametrize(("method", "args"), SENDS)
def test_fake_refuses_every_send_to_a_group(fake_channel, method, args):
    with pytest.raises(GroupSendForbidden):
        getattr(fake_channel, method)(*args)

    assert fake_channel.sent == []


@pytest.mark.parametrize(("method", "args"), SENDS)
def test_allow_group_is_an_explicit_opt_in(fake_channel, method, args):
    getattr(fake_channel, method)(*args, allow_group=True)

    assert len(fake_channel.sent) == 1


@pytest.mark.parametrize(("method", "args"), SENDS)
def test_wasender_allow_group_opt_in(method, args):
    channel, requests = _wasender()

    getattr(channel, method)(*args, allow_group=True)

    assert len(requests) == 1


def test_group_send_forbidden_is_not_a_swallowable_channel_error():
    from tchekam.messaging.channel import ChannelError

    assert not issubclass(GroupSendForbidden, ChannelError)


@pytest.mark.parametrize(
    ("jid", "expected"),
    [
        (GROUP, True),
        (" 120363@G.US ", True),
        ("237670000001", False),
        ("237670000001@s.whatsapp.net", False),
        ("123@lid", False),
        ("", False),
    ],
)
def test_is_group_jid(jid, expected):
    assert is_group_jid(jid) is expected


def test_private_sends_still_work(fake_channel):
    fake_channel.send_text("237670000001", "hi")

    assert fake_channel.sent == [{"type": "text", "to": "237670000001", "text": "hi"}]
