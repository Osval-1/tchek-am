import pytest

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


@pytest.mark.django_db
def test_channel_failure_marks_failed_with_class_name_only(payload, fake_channel, monkeypatch):
    def fail(to, text):
        raise RateLimited(30)

    monkeypatch.setattr(fake_channel, "send_text", fail)
    event = _event(payload)

    process_inbound(event_id=event.pk)

    event.refresh_from_db()
    assert event.status == InboundEvent.Status.FAILED
    assert event.error == "RateLimited"
    assert event.processed_at is None


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
