import threading
import time
from datetime import timedelta

import pytest
from django.db import connection
from django.db.models import F
from django.utils import timezone

from tchekam.messaging import outbox, tasks
from tchekam.messaging.channel import RateLimited
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.tasks import process_inbound


def _event(payload, fixture="private_text_received"):
    data = payload(fixture)
    return InboundEvent.objects.create(
        message_id=data["data"]["messages"]["key"]["id"], event=data["event"], payload=data
    )


@pytest.mark.django_db
def test_processed_event_is_not_handled_twice(payload, fake_channel):
    event = _event(payload)

    process_inbound(event_id=event.pk)
    process_inbound(event_id=event.pk)

    assert len(fake_channel.sent) == 1


@pytest.fixture
def enqueued(monkeypatch):
    """Capture re-enqueues instead of running them inline (tests are eager)."""
    calls = []
    monkeypatch.setattr(tasks, "enqueue", lambda name, **kw: calls.append((name, kw)))
    monkeypatch.setattr(outbox, "enqueue", lambda name, **kw: calls.append((name, kw)))
    return calls


@pytest.mark.django_db
def test_rate_limited_send_defers_only_the_unsent_replies(
    payload, fake_channel, monkeypatch, enqueued
):
    def fail(to, text):
        raise RateLimited(30)

    monkeypatch.setattr(fake_channel, "send_text", fail)
    event = _event(payload)

    process_inbound(event_id=event.pk)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.PROCESSED  # routing is done; never re-run
    ((name, kwargs),) = enqueued
    assert name == "messaging.deliver_replies"
    assert kwargs["schedule_in_seconds"] >= 30
    assert kwargs["queue"] == "whatsapp"
    assert kwargs["items"][0]["text"]


@pytest.mark.django_db
def test_rate_limit_before_any_reply_requeues_the_event_with_class_name_only(
    payload, monkeypatch, enqueued
):
    def limited(msg):
        raise RateLimited(45)

    monkeypatch.setattr(tasks, "_handle", limited)
    event = _event(payload)

    process_inbound(event_id=event.pk)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.RECEIVED
    assert event.claimed_at is None
    assert event.error == "RateLimited"
    ((name, kwargs),) = enqueued
    assert name == "messaging.process_inbound"
    assert kwargs["schedule_in_seconds"] >= 45
    assert kwargs["deferrals"] == 1


@pytest.mark.django_db
def test_rate_limit_deferrals_are_capped(payload, monkeypatch, enqueued):
    def limited(msg):
        raise RateLimited(5)

    monkeypatch.setattr(tasks, "_handle", limited)
    event = _event(payload)

    process_inbound(event_id=event.pk, deferrals=outbox.MAX_DEFERRALS)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.FAILED
    assert event.error == "RateLimited"
    assert enqueued == []


@pytest.mark.django_db
def test_other_errors_retry_with_backoff_then_fail(payload, monkeypatch, enqueued):
    def boom(msg):
        raise RuntimeError("secret text 237670000001")

    monkeypatch.setattr(tasks, "_handle", boom)
    event = _event(payload)

    process_inbound(event_id=event.pk)
    event.refresh_from_db()
    assert event.status == InboundEvent.Status.RECEIVED
    assert event.attempts == 1
    assert enqueued[0][1]["schedule_in_seconds"] == tasks.BACKOFF_SECONDS
    assert enqueued[0][1]["lock"] == outbox.lock_for("237670000001")  # the sender's lock

    process_inbound(event_id=event.pk)
    assert enqueued[1][1]["schedule_in_seconds"] == tasks.BACKOFF_SECONDS * 2

    process_inbound(event_id=event.pk)
    event.refresh_from_db()
    assert event.status == InboundEvent.Status.FAILED
    assert event.error == "RuntimeError"
    assert len(enqueued) == 2


@pytest.mark.django_db
def test_rate_limit_requeues_cost_no_attempts(payload, monkeypatch, enqueued):
    def limited(msg):
        raise RateLimited(5)

    monkeypatch.setattr(tasks, "_handle", limited)
    event = _event(payload)

    for _ in range(5):
        process_inbound(event_id=event.pk)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.RECEIVED
    assert event.attempts == 0


@pytest.mark.django_db
def test_limiter_database_error_after_routing_does_not_route_twice(
    payload, fake_channel, settings, monkeypatch, enqueued
):
    from django.db import OperationalError

    from tchekam.conversations.models import Conversation
    from tchekam.messaging import limiter

    settings.CHANNEL_SAFEGUARDS = True

    def broken(to):
        raise OperationalError("connection lost")

    monkeypatch.setattr(limiter, "acquire", broken)
    event = _event(payload)

    process_inbound(event_id=event.pk)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.FAILED
    assert event.error == "OperationalError"
    assert enqueued == []  # no retry: the message was routed once
    assert Conversation.objects.count() == 1


@pytest.mark.django_db
def test_error_in_a_delivered_callback_does_not_route_twice(payload, monkeypatch, enqueued):
    from tchekam.conversations import service

    def failing_callback():
        raise RuntimeError("callback")

    def hook(user, conversation, replies):
        return service.HookResult([], failing_callback)

    monkeypatch.setattr(service, "_AFTER_ROUTE_HOOKS", [hook])
    event = _event(payload)

    process_inbound(event_id=event.pk)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.FAILED
    assert enqueued == []


@pytest.mark.django_db
def test_incomplete_delivery_fails_without_rerunning_the_event(
    payload, fake_channel, monkeypatch, enqueued
):
    monkeypatch.setattr(outbox, "deliver", lambda *a, **k: outbox.ABANDONED)
    event = _event(payload)

    process_inbound(event_id=event.pk)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.FAILED
    assert event.error == "DeliveryIncomplete"
    assert enqueued == []


@pytest.mark.django_db
def test_claimed_event_is_not_taken_again(payload, fake_channel):
    event = _event(payload)
    InboundEvent.objects.filter(pk=event.pk).update(status=InboundEvent.Status.PROCESSING)

    process_inbound(event_id=event.pk)

    assert fake_channel.sent == []


@pytest.mark.django_db
def test_stuck_processing_event_is_recovered(payload, fake_channel, enqueued):
    stuck = _event(payload)
    fresh = InboundEvent.objects.create(message_id="F", event="e", payload={})
    now = timezone.now()
    InboundEvent.objects.filter(pk=stuck.pk).update(
        status=InboundEvent.Status.PROCESSING, claimed_at=now - timedelta(minutes=11)
    )
    InboundEvent.objects.filter(pk=fresh.pk).update(
        status=InboundEvent.Status.PROCESSING, claimed_at=now - timedelta(minutes=2)
    )

    assert tasks.recover_stuck_events() == 1

    stuck.refresh_from_db()
    fresh.refresh_from_db()
    assert stuck.status == InboundEvent.Status.RECEIVED
    assert fresh.status == InboundEvent.Status.PROCESSING
    assert [kw["event_id"] for _, kw in enqueued] == [stuck.pk]


@pytest.mark.django_db
def test_recovered_event_is_processed(payload, fake_channel):
    event = _event(payload)
    InboundEvent.objects.filter(pk=event.pk).update(
        status=InboundEvent.Status.PROCESSING, claimed_at=timezone.now() - timedelta(hours=1)
    )

    tasks.recover_stuck_events()  # eager: re-enqueues by running it

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.PROCESSED
    assert len(fake_channel.sent) == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_runs_for_one_event_send_one_reply(payload, fake_channel, monkeypatch):
    event = _event(payload)
    original = fake_channel.send_text
    calls = []

    def slow_send(to, text):
        calls.append(to)
        time.sleep(0.4)  # hold the claim open while the second worker arrives
        original(to, text)

    monkeypatch.setattr(fake_channel, "send_text", slow_send)
    errors = []

    def run():
        try:
            process_inbound(event_id=event.pk)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
        time.sleep(0.1)
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(calls) == 1
    event.refresh_from_db()
    assert event.status == InboundEvent.Status.PROCESSED


@pytest.mark.django_db
def test_missing_event_is_a_no_op(fake_channel):
    process_inbound(event_id=999_999)

    assert fake_channel.sent == []


@pytest.mark.django_db
def test_unparseable_stored_payload_is_ignored(fake_channel):
    event = InboundEvent.objects.create(message_id="X", event="weird", payload={"data": {}})

    process_inbound(event_id=event.pk)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.IGNORED
    assert fake_channel.sent == []


@pytest.mark.django_db
def test_failure_logs_no_message_body(payload, fake_channel, monkeypatch, caplog):
    def fail(to, text):
        raise RuntimeError(f"boom {to} {text}")

    monkeypatch.setattr(fake_channel, "send_text", fail)
    event = _event(payload)

    process_inbound(event_id=event.pk)

    assert "Hello bot" not in caplog.text
    assert "237670000001" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.django_db
def test_reply_goes_out_through_the_safeguards(payload, fake_channel, settings, monkeypatch):
    from tchekam.messaging import safe

    settings.CHANNEL_SAFEGUARDS = True
    monkeypatch.setattr(safe, "_sleep", lambda seconds: None)
    event = _event(payload)

    process_inbound(event_id=event.pk)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.PROCESSED
    assert [m["type"] for m in fake_channel.sent] == ["typing", "text"]


@pytest.mark.django_db
def test_a_crash_three_times_ends_failed(payload, fake_channel, enqueued):
    event = _event(payload)
    old = timezone.now() - timedelta(hours=1)

    for _ in range(tasks.MAX_ATTEMPTS):
        # The worker claims, then dies before finishing.
        InboundEvent.objects.filter(pk=event.pk, status=InboundEvent.Status.RECEIVED).update(
            status=InboundEvent.Status.PROCESSING, claimed_at=old, attempts=F("attempts") + 1
        )
        tasks.recover_stuck_events()

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.FAILED
    assert event.error == "StuckProcessing"
    assert len(enqueued) == tasks.MAX_ATTEMPTS - 1
