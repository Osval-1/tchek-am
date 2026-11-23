import json

import httpx
import pytest

from tchekam.messaging.channel import ChannelError, MediaTooLarge, RateLimited
from tchekam.messaging.parser import parse_wasender_payload
from tchekam.messaging.wasender import WaSenderChannel

BASE = "https://wasender.test/api"


class Recorder:
    def __init__(self, responder):
        self.requests: list[httpx.Request] = []
        self.responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)

    @property
    def last_json(self):
        return json.loads(self.requests[-1].content)


def ok(_request):
    return httpx.Response(200, json={"success": True, "data": {"msgId": 1, "status": "ok"}})


def make(responder=ok):
    rec = Recorder(responder)
    channel = WaSenderChannel(api_key="sess-key", base_url=BASE, transport=httpx.MockTransport(rec))
    return channel, rec


def test_send_text_posts_json_with_bearer():
    channel, rec = make()

    channel.send_text("237670000001", "hi")

    req = rec.requests[0]
    assert req.method == "POST"
    assert str(req.url) == f"{BASE}/send-message"
    assert req.headers["Authorization"] == "Bearer sess-key"
    assert req.headers["Content-Type"] == "application/json"
    assert rec.last_json == {"to": "237670000001", "text": "hi"}


def test_send_image_with_and_without_caption():
    channel, rec = make()

    channel.send_image("237670000001", "https://r2/x.jpg", caption="cap")
    assert rec.last_json == {"to": "237670000001", "imageUrl": "https://r2/x.jpg", "text": "cap"}

    channel.send_image("237670000001", "https://r2/x.jpg")
    assert rec.last_json == {"to": "237670000001", "imageUrl": "https://r2/x.jpg"}


def test_send_typing():
    channel, rec = make()

    channel.send_typing("237670000001@s.whatsapp.net", 1500)

    assert str(rec.requests[0].url) == f"{BASE}/send-presence-update"
    assert rec.last_json == {
        "jid": "237670000001@s.whatsapp.net",
        "type": "composing",
        "delayMs": 1500,
    }


def test_leave_group():
    channel, rec = make()

    channel.leave_group("1203@g.us")

    assert rec.requests[0].method == "POST"
    assert rec.requests[0].url.path == "/api/groups/1203@g.us/leave"


def test_group_metadata_returns_data():
    meta = {"subject": "Market", "participants": [{"jid": "a@lid", "isAdmin": True}]}
    channel, rec = make(lambda r: httpx.Response(200, json={"success": True, "data": meta}))

    assert channel.group_metadata("1203@g.us") == meta
    assert rec.requests[0].method == "GET"
    assert rec.requests[0].url.path == "/api/groups/1203@g.us/metadata"


def test_retry_after_body_raises_rate_limited_even_without_429():
    channel, _ = make(
        lambda r: httpx.Response(400, json={"success": False, "message": "x", "retry_after": 42})
    )

    with pytest.raises(RateLimited) as exc:
        channel.send_text("237670000001", "hi")

    assert exc.value.retry_after == 42


def test_http_429_without_body_defaults_retry_after():
    channel, _ = make(lambda r: httpx.Response(429, text="slow down"))

    with pytest.raises(RateLimited) as exc:
        channel.send_text("237670000001", "hi")

    assert exc.value.retry_after == 60


def test_rate_limited_is_a_channel_error():
    assert issubclass(RateLimited, ChannelError)


def test_error_response_raises_channel_error_without_message_body():
    channel, _ = make(
        lambda r: httpx.Response(422, json={"success": False, "message": "bad", "errors": {}})
    )

    with pytest.raises(ChannelError) as exc:
        channel.send_text("237670000001", "secret text")

    assert "secret text" not in str(exc.value)
    assert "237670000001" not in str(exc.value)
    assert not isinstance(exc.value, RateLimited)


def test_success_false_with_200_is_an_error():
    channel, _ = make(lambda r: httpx.Response(200, json={"success": False, "message": "no"}))

    with pytest.raises(ChannelError):
        channel.send_text("237670000001", "hi")


def test_transport_error_becomes_channel_error():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    channel, _ = make(boom)

    with pytest.raises(ChannelError):
        channel.send_text("237670000001", "hi")


def test_download_media_decrypts_then_fetches(payload):
    msg = parse_wasender_payload(payload("image_caption"))

    def responder(request):
        if request.url.path == "/api/decrypt-media":
            return httpx.Response(200, json={"success": True, "publicUrl": "https://cdn.test/f"})
        if request.url.host == "cdn.test":
            return httpx.Response(200, content=b"JPEGDATA", headers={"Content-Type": "image/jpeg"})
        return httpx.Response(404)

    channel, rec = make(responder)

    data, mimetype = channel.download_media(msg)

    assert (data, mimetype) == (b"JPEGDATA", "image/jpeg")
    body = json.loads(rec.requests[0].content)
    image = body["data"]["messages"]["message"]["imageMessage"]
    assert body["data"]["messages"]["key"] == {"id": "MSG-IMG-1"}
    assert image["mediaKey"] == "bWVkaWFrZXk="
    assert "type" not in image
    # The public URL is not ours: the API key must not leak to it.
    assert "Authorization" not in rec.requests[1].headers


def test_download_media_follows_redirects(payload):
    msg = parse_wasender_payload(payload("image_caption"))

    def responder(request):
        if request.url.path == "/api/decrypt-media":
            return httpx.Response(200, json={"success": True, "publicUrl": "https://cdn.test/f"})
        if request.url.path == "/f":
            return httpx.Response(302, headers={"Location": "https://cdn.test/real"})
        return httpx.Response(200, content=b"REAL", headers={"Content-Type": "image/png"})

    channel, _ = make(responder)

    assert channel.download_media(msg) == (b"REAL", "image/png")


def test_download_media_falls_back_to_descriptor_mimetype(payload):
    msg = parse_wasender_payload(payload("audio"))

    def responder(request):
        if request.url.path == "/api/decrypt-media":
            return httpx.Response(200, json={"success": True, "publicUrl": "https://cdn.test/a"})
        return httpx.Response(200, content=b"OGG")

    channel, _ = make(responder)

    assert channel.download_media(msg) == (b"OGG", "audio/ogg; codecs=opus")


def test_download_media_rejects_oversize(payload):
    msg = parse_wasender_payload(payload("image_caption"))

    def responder(request):
        if request.url.path == "/api/decrypt-media":
            return httpx.Response(200, json={"success": True, "publicUrl": "https://cdn.test/f"})
        return httpx.Response(200, content=b"x" * (16 * 1024 * 1024 + 1))

    channel, _ = make(responder)

    with pytest.raises(MediaTooLarge):
        channel.download_media(msg)


def test_download_media_without_media_raises(payload):
    msg = parse_wasender_payload(payload("private_text_received"))
    channel, rec = make()

    with pytest.raises(ChannelError):
        channel.download_media(msg)
    assert rec.requests == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [(42, 42), ("7", 7), (99999, 3600), (0, 1), (-5, 1), ("nan", 60), ("inf", 60), ("x", 60)],
)
def test_retry_after_is_clamped_and_defensive(value, expected):
    channel, _ = make(lambda r: httpx.Response(429, json={"retry_after": value}))

    with pytest.raises(RateLimited) as exc:
        channel.send_text("237670000001", "hi")

    assert exc.value.retry_after == expected
