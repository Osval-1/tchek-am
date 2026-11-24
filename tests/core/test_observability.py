import json

import pytest
import sentry_sdk
import sentry_sdk.transport

from tchekam.core import observability

PHONE = "+237677123456"
MASKED = "+237*******56"


def test_scrub_masks_phones_in_messages_exceptions_and_breadcrumbs():
    event = {
        "message": f"failed for {PHONE}",
        "logentry": {"message": "send to %s", "formatted": f"send to {PHONE}", "params": [PHONE]},
        "exception": {"values": [{"type": "ValueError", "value": f"bad {PHONE}"}]},
        "breadcrumbs": {
            "values": [{"message": f"to {PHONE}", "data": {"to": PHONE, "n": 3}, "type": "log"}]
        },
        "extra": {"who": [PHONE]},
        "event_id": "20261124202611242026112420261124",
        "timestamp": "2026-11-24T10:00:00Z",
    }

    out = observability.scrub_event(event, {})

    assert out["message"] == f"failed for {MASKED}"
    assert out["logentry"]["formatted"] == f"send to {MASKED}"
    assert out["logentry"]["params"] == [MASKED]
    assert out["exception"]["values"][0]["value"] == f"bad {MASKED}"
    crumb = out["breadcrumbs"]["values"][0]
    assert crumb["message"] == f"to {MASKED}" and crumb["data"] == {"to": MASKED, "n": 3}
    assert out["extra"] == {"who": [MASKED]}
    # Identifiers and timestamps are not phone numbers.
    assert out["event_id"] == event["event_id"] and out["timestamp"] == event["timestamp"]


def test_scrub_drops_request_bodies_headers_cookies_and_locals():
    event = {
        "request": {
            "url": "https://x.example/webhooks/whatsapp",
            "method": "POST",
            "data": {"messageBody": "hello"},
            "headers": {"X-Webhook-Signature": "s3cret"},
            "cookies": {"sessionid": "abc"},
            "query_string": f"phone={PHONE}",
            "env": {"REMOTE_ADDR": "1.2.3.4"},
        },
        "user": {"ip_address": "1.2.3.4"},
        "exception": {
            "values": [
                {"value": "x", "stacktrace": {"frames": [{"function": "f", "vars": {"a": PHONE}}]}}
            ]
        },
    }

    out = observability.scrub_event(event, {})

    assert out["request"] == {"url": "https://x.example/webhooks/whatsapp", "method": "POST"}
    assert "user" not in out
    assert out["exception"]["values"][0]["stacktrace"]["frames"] == [{"function": "f"}]


def test_scrub_tolerates_a_bare_event():
    assert observability.scrub_event({}, {}) == {}


def test_init_sentry_is_a_noop_without_a_dsn(monkeypatch):
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))

    assert observability.init_sentry(dsn="", environment="prod", release="r") is False
    assert calls == []


def test_init_sentry_configures_a_privacy_preserving_client(monkeypatch):
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))

    assert observability.init_sentry(dsn="https://k@o.example/1", environment="prod", release="abc")

    (kw,) = calls
    assert kw["send_default_pii"] is False
    assert kw["before_send"] is observability.scrub_event
    assert kw["max_request_body_size"] == "never"
    assert kw["include_local_variables"] is False
    assert kw["traces_sample_rate"] == 0.0
    assert (kw["environment"], kw["release"]) == ("prod", "abc")
    assert kw["dsn"] == "https://k@o.example/1"


class CapturingTransport(sentry_sdk.transport.Transport):
    def __init__(self):
        super().__init__()
        self.events = []

    def capture_envelope(self, envelope):
        self.events += [i.payload.json for i in envelope.items if i.type == "event"]


@pytest.fixture
def real_sentry():
    transport = CapturingTransport()
    # The real init, so an option the installed SDK rejects fails here, not at deploy.
    assert observability.init_sentry(
        dsn="https://k@o.example/1", environment="test", release="r", transport=transport
    )
    yield transport
    sentry_sdk.init()  # back to a disabled client


def test_real_sdk_init_accepts_our_options_and_scrubs_a_captured_exception(real_sentry):
    def add_request(event, hint):
        event["request"] = {
            "url": "https://x.example/webhooks/whatsapp",
            "method": "POST",
            "data": "messageBody",
            "headers": {"X-Webhook-Signature": "s3cret"},
            "cookies": {"sessionid": "abc"},
        }
        event["user"] = {"id": "1", "ip_address": "1.2.3.4"}
        return event

    sentry_sdk.get_current_scope().add_event_processor(add_request)
    sentry_sdk.add_breadcrumb(message=f"to {PHONE}", data={"to": PHONE})
    try:
        secret_local = PHONE  # noqa: F841 - would appear in frame vars if they were sent
        raise ValueError(f"bad number {PHONE}")
    except ValueError as exc:
        sentry_sdk.capture_exception(exc)
    sentry_sdk.flush()

    (event,) = real_sentry.events
    text = json.dumps(event)
    assert "677123456" not in text
    assert MASKED in text
    assert event["request"] == {"url": "https://x.example/webhooks/whatsapp", "method": "POST"}
    assert "user" not in event
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    assert all("vars" not in f for f in frames)
    assert "s3cret" not in text
