from datetime import timedelta

import pytest
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.messaging import limiter, safe
from tchekam.messaging.channel import (
    ChannelError,
    Deferred,
    GroupSendForbidden,
    RateLimited,
    UnsolicitedMessageBlocked,
    get_channel,
)
from tchekam.messaging.models import RecipientSend, SendBucket

PHONE = "237670000001"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def safeguards(settings, monkeypatch):
    settings.CHANNEL_SAFEGUARDS = True
    slept = []
    monkeypatch.setattr(safe, "_sleep", slept.append)
    return slept


@pytest.fixture
def slept(safeguards):
    return safeguards


@pytest.fixture
def user():
    return BotUser.objects.create(wa_phone=f"+{PHONE}", last_inbound_at=timezone.now())


def test_get_channel_wraps_only_when_enabled(settings, fake_channel):
    assert isinstance(get_channel(), safe.SafeChannel)
    settings.CHANNEL_SAFEGUARDS = False
    assert get_channel() is fake_channel


def test_no_inbound_message_in_the_window_is_blocked(fake_channel):
    BotUser.objects.create(wa_phone=f"+{PHONE}", last_inbound_at=None)

    with pytest.raises(UnsolicitedMessageBlocked):
        get_channel().send_text(PHONE, "hi")

    assert fake_channel.sent == []


def test_unknown_recipient_and_stale_inbound_are_blocked(fake_channel):
    with pytest.raises(UnsolicitedMessageBlocked):
        get_channel().send_text(PHONE, "hi")
    BotUser.objects.create(
        wa_phone=f"+{PHONE}", last_inbound_at=timezone.now() - timedelta(hours=25)
    )

    with pytest.raises(UnsolicitedMessageBlocked):
        get_channel().send_image(PHONE, "https://x/y.png")


def test_blocked_is_a_channel_error():
    assert issubclass(UnsolicitedMessageBlocked, ChannelError)


def test_allow_unsolicited_skips_the_window_for_that_recipient_only(fake_channel):
    with safe.allow_unsolicited(PHONE):
        get_channel().send_text(PHONE, "hi")
        with pytest.raises(UnsolicitedMessageBlocked):
            get_channel().send_text("237670000002", "hi")
    with pytest.raises(UnsolicitedMessageBlocked):
        get_channel().send_text(PHONE, "hi")


def test_group_target_is_refused_before_anything_else(fake_channel):
    with pytest.raises(GroupSendForbidden):
        get_channel().send_text("123@g.us", "hi")
    assert RecipientSend.objects.count() == 0


def test_typing_comes_first_with_the_computed_delay(user, fake_channel, slept):
    get_channel().send_text(PHONE, "x" * 10)

    assert fake_channel.sent == [
        {"type": "typing", "jid": PHONE, "ms": 400},
        {"type": "text", "to": PHONE, "text": "x" * 10},
    ]
    assert slept == [0.4]


def test_typing_delay_is_capped(user, fake_channel, slept):
    get_channel().send_text(PHONE, "x" * 500)

    assert fake_channel.sent[0]["ms"] == 4000
    assert slept == [4.0]


def test_typing_failure_is_swallowed(user, fake_channel, monkeypatch):
    def broken(jid, ms, **kwargs):
        raise ChannelError("typing down")

    monkeypatch.setattr(fake_channel, "send_typing", broken)

    get_channel().send_text(PHONE, "hello")

    assert [m["type"] for m in fake_channel.sent] == ["text"]


def test_typing_rate_limit_is_not_swallowed(user, fake_channel, monkeypatch):
    def limited(jid, ms, **kwargs):
        raise RateLimited(7)

    monkeypatch.setattr(fake_channel, "send_typing", limited)

    with pytest.raises(RateLimited) as caught:
        get_channel().send_text(PHONE, "hello")

    assert caught.value.retry_after == 7
    assert fake_channel.sent == []


def test_images_have_no_typing_and_other_calls_pass_through(user, fake_channel):
    channel = get_channel()
    channel.send_image(PHONE, "https://x/y.png", "cap")
    channel.send_typing(PHONE, 100)
    channel.leave_group("g@g.us")
    fake_channel.groups["g@g.us"] = {"subject": "S"}

    assert channel.group_metadata("g@g.us") == {"subject": "S"}
    assert [m["type"] for m in fake_channel.sent] == ["image", "typing", "leave_group"]


def test_download_media_passes_through(user, fake_channel, payload):
    from tchekam.messaging.parser import parse_wasender_payload

    fake_channel.media["MSG-IMG-1"] = (b"img", "image/png")
    msg = parse_wasender_payload(payload("image_caption"))

    assert get_channel().download_media(msg) == (b"img", "image/png")


def test_seventh_send_within_thirty_seconds_is_deferred(user, fake_channel):
    channel = get_channel()
    for _ in range(6):
        channel.send_text(PHONE, "hi")

    with pytest.raises(Deferred) as caught:
        channel.send_text(PHONE, "hi")

    assert 1 <= caught.value.retry_after <= 30
    assert isinstance(caught.value, RateLimited)
    assert len([m for m in fake_channel.sent if m["type"] == "text"]) == 6


def test_window_slides_and_old_rows_are_pruned(user, fake_channel):
    channel = get_channel()
    for _ in range(6):
        channel.send_text(PHONE, "hi")
    RecipientSend.objects.update(sent_at=timezone.now() - timedelta(seconds=31))

    channel.send_text(PHONE, "again")

    assert RecipientSend.objects.count() == 1


def test_other_recipients_are_not_affected(user, fake_channel):
    other = BotUser.objects.create(wa_phone="+237670000002", last_inbound_at=timezone.now())
    channel = get_channel()
    for _ in range(6):
        channel.send_text(PHONE, "hi")

    channel.send_text(other.wa_phone.lstrip("+"), "hi")


def test_recipients_are_stored_hashed(user, fake_channel):
    get_channel().send_text(PHONE, "hi")

    (row,) = RecipientSend.objects.all()
    assert PHONE not in row.recipient_hash
    assert row.recipient_hash == limiter.recipient_hash(PHONE)


def test_global_bucket_defers_when_empty(user, fake_channel, settings):
    settings.SEND_RATE_PER_MINUTE = 2
    users = [
        BotUser.objects.create(wa_phone=f"+23767000010{i}", last_inbound_at=timezone.now())
        for i in range(3)
    ]
    channel = get_channel()
    channel.send_text(users[0].wa_phone.lstrip("+"), "a")
    channel.send_text(users[1].wa_phone.lstrip("+"), "b")

    with pytest.raises(Deferred) as caught:
        channel.send_text(users[2].wa_phone.lstrip("+"), "c")

    assert caught.value.retry_after == 30  # 2 per minute: one token every 30 s


def test_global_bucket_refills_over_time(user, fake_channel, settings):
    settings.SEND_RATE_PER_MINUTE = 2
    channel = get_channel()
    channel.send_text(PHONE, "a")
    channel.send_text(PHONE, "b")
    SendBucket.objects.update(updated_at=timezone.now() - timedelta(seconds=40))

    channel.send_text(PHONE, "c")  # refilled by about 1.3 tokens


def test_a_deferral_charges_nothing(user, fake_channel, settings):
    settings.SEND_RATE_PER_MINUTE = 1
    channel = get_channel()
    channel.send_text(PHONE, "a")

    with pytest.raises(Deferred):
        channel.send_text(PHONE, "b")

    assert RecipientSend.objects.count() == 1
