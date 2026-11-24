import logging

import pytest
from django.utils import timezone

from tchekam.conversations import outbound
from tchekam.conversations.models import BotUser
from tchekam.messaging import outbox, tasks
from tchekam.messaging.channel import ChannelError, RateLimited, UnsolicitedMessageBlocked

PHONE = "237670000001"
ITEMS = [{"text": "one", "image_url": None}, {"text": "two", "image_url": None}]

pytestmark = pytest.mark.django_db


@pytest.fixture
def scheduled(monkeypatch):
    calls = []
    monkeypatch.setattr(outbox, "enqueue", lambda name, **kw: calls.append((name, kw)))
    return calls


def test_everything_sent(fake_channel, scheduled):
    items = ITEMS + [{"text": "cap", "image_url": "https://x/y.png"}]

    assert outbox.deliver(PHONE, items) == outbox.SENT

    assert [m["type"] for m in fake_channel.sent] == ["text", "text", "image"]
    assert scheduled == []


def test_rate_limit_requeues_only_the_unsent_tail_with_at_least_retry_after(
    fake_channel, scheduled, monkeypatch
):
    original = fake_channel.send_text

    def limited_on_two(to, text):
        if text == "two":
            raise RateLimited(42)
        original(to, text)

    monkeypatch.setattr(fake_channel, "send_text", limited_on_two)

    assert outbox.deliver(PHONE, ITEMS) == outbox.DEFERRED

    assert [m["text"] for m in fake_channel.sent] == ["one"]
    ((name, kwargs),) = scheduled
    assert name == "messaging.deliver_replies"
    assert kwargs["schedule_in_seconds"] >= 42
    assert kwargs["queue"] == "whatsapp"
    assert kwargs["lock"] == outbox.lock_for(PHONE)
    assert kwargs["items"] == ITEMS[1:]
    assert kwargs["deferrals"] == 1


def test_deferrals_are_capped(fake_channel, scheduled, monkeypatch):
    def limited(to, text):
        raise RateLimited(1)

    monkeypatch.setattr(fake_channel, "send_text", limited)

    assert outbox.deliver(PHONE, ITEMS, deferrals=outbox.MAX_DEFERRALS) == outbox.ABANDONED
    assert scheduled == []


def test_generic_errors_back_off_then_give_up(fake_channel, scheduled, monkeypatch, caplog):
    def broken(to, text):
        raise ChannelError(f"boom {to} {text}")

    monkeypatch.setattr(fake_channel, "send_text", broken)

    assert outbox.deliver(PHONE, ITEMS) == outbox.RETRYING
    assert scheduled[0][1]["schedule_in_seconds"] == outbox.BACKOFF_SECONDS
    assert scheduled[0][1]["attempt"] == 1

    with caplog.at_level(logging.INFO):
        assert outbox.deliver(PHONE, ITEMS, attempt=outbox.MAX_ATTEMPTS - 1) == outbox.ABANDONED
    assert "ChannelError" in caplog.text
    assert PHONE not in caplog.text
    assert len(scheduled) == 1


def test_blocked_replies_are_dropped_not_retried(fake_channel, scheduled, monkeypatch):
    def blocked(to, text):
        raise UnsolicitedMessageBlocked("no")

    monkeypatch.setattr(fake_channel, "send_text", blocked)

    assert outbox.deliver(PHONE, ITEMS) == outbox.ABANDONED
    assert scheduled == []


def test_blank_items_are_skipped(fake_channel):
    assert outbox.deliver(PHONE, [{"text": None, "image_url": None}]) == outbox.SENT
    assert fake_channel.sent == []


def test_lock_is_stable_and_spread_over_three_names():
    names = {outbox.lock_for(f"2376700000{i:02d}") for i in range(40)}

    assert names == {"whatsapp-0", "whatsapp-1", "whatsapp-2"}
    assert outbox.lock_for(PHONE) == outbox.lock_for(PHONE)


def test_deliver_replies_task_runs_the_outbox(fake_channel):
    tasks.deliver_replies(to=PHONE, items=ITEMS)

    assert [m["text"] for m in fake_channel.sent] == ["one", "two"]


def test_send_to_user_queues_on_the_whatsapp_queue_instead_of_sending(fake_channel, scheduled):
    user = BotUser.objects.create(wa_phone=f"+{PHONE}", last_inbound_at=timezone.now())

    assert outbound.send_to_user(user, text="your result") is True

    assert fake_channel.sent == []
    ((name, kwargs),) = scheduled
    assert name == "messaging.deliver_replies"
    assert kwargs["queue"] == "whatsapp"
    assert kwargs["lock"] == outbox.lock_for(PHONE)
    assert kwargs["items"] == [{"text": "your result", "image_url": None}]


def test_send_to_user_without_defer_reports_failure(fake_channel, scheduled, monkeypatch):
    user = BotUser.objects.create(wa_phone=f"+{PHONE}", last_inbound_at=timezone.now())

    def limited(to, text):
        raise RateLimited(9)

    monkeypatch.setattr(fake_channel, "send_text", limited)

    assert outbound.send_to_user(user, text="x", defer=False) is False
    assert scheduled == []


def test_send_to_user_image_without_defer(fake_channel):
    user = BotUser.objects.create(wa_phone=f"+{PHONE}", last_inbound_at=timezone.now())

    assert outbound.send_to_user(user, text="cap", image_url="https://x/y.png", defer=False)
    assert fake_channel.sent[0]["type"] == "image"


def test_queued_send_to_a_user_outside_the_window_is_dropped_by_the_job(settings, fake_channel):
    settings.CHANNEL_SAFEGUARDS = True
    user = BotUser.objects.create(wa_phone=f"+{PHONE}", last_inbound_at=None)

    outbound.send_to_user(user, text="hello?")  # eager: the job runs inline

    assert fake_channel.sent == []
