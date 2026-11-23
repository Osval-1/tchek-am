import json

import pytest

from tchekam.conversations.models import BotUser
from tchekam.core import tasks
from tchekam.i18n import t
from tchekam.messaging import hooks
from tchekam.messaging.models import InboundEvent

URL = "/webhooks/whatsapp"
SECRET = "test-webhook-secret"


@pytest.fixture(autouse=True)
def _secret(settings):
    settings.WASENDER_WEBHOOK_SECRET = SECRET


@pytest.fixture
def enqueued(monkeypatch):
    """Record every enqueue while still running the task (eager in tests)."""
    calls = []
    original = tasks.enqueue

    def spy(name, **kwargs):
        calls.append((name, kwargs))
        return original(name, **kwargs)

    monkeypatch.setattr(tasks, "enqueue", spy)
    return calls


def post(client, body, signature=SECRET):
    headers = {} if signature is None else {"X-Webhook-Signature": signature}
    data = body if isinstance(body, str) else json.dumps(body)
    return client.post(URL, data=data, content_type="application/json", headers=headers)


@pytest.mark.django_db
@pytest.mark.parametrize("signature", [None, "", "wrong-secret", SECRET + "x", "é"])
def test_bad_signature_is_401_and_stores_nothing(
    client, payload, enqueued, django_capture_on_commit_callbacks, signature
):
    with django_capture_on_commit_callbacks(execute=True):
        response = post(client, payload("private_text_received"), signature=signature)

    assert response.status_code == 401
    assert InboundEvent.objects.count() == 0
    assert enqueued == []


@pytest.mark.django_db
def test_empty_secret_setting_fails_closed(client, payload, settings):
    settings.WASENDER_WEBHOOK_SECRET = ""

    response = post(client, payload("private_text_received"), signature="")

    assert response.status_code == 401
    assert InboundEvent.objects.count() == 0


@pytest.mark.django_db
def test_only_post_is_allowed(client):
    response = client.get(URL, headers={"X-Webhook-Signature": SECRET})

    assert response.status_code == 405


@pytest.mark.django_db
def test_invalid_json_is_400(client):
    response = post(client, "{not json")

    assert response.status_code == 400
    assert InboundEvent.objects.count() == 0


@pytest.mark.django_db
def test_valid_payload_stores_one_event_and_enqueues_once(
    client, payload, enqueued, fake_channel, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = post(client, payload("private_text_received"))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    event = InboundEvent.objects.get()
    assert event.message_id == "MSG-PRIV-1"
    assert event.event == "messages.received"
    assert event.payload == payload("private_text_received")
    assert enqueued == [("messaging.process_inbound", {"event_id": event.pk})]


@pytest.mark.django_db
def test_duplicate_payload_is_200_without_new_row_or_enqueue(
    client, payload, enqueued, fake_channel, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        post(client, payload("private_text_received"))
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = post(client, payload("private_text_received"))

    assert response.status_code == 200
    assert InboundEvent.objects.count() == 1
    assert len(enqueued) == 1
    assert callbacks == []
    assert len(fake_channel.sent) == 1


@pytest.mark.django_db
def test_enqueue_waits_for_commit(client, payload, enqueued, fake_channel):
    # Inside the test transaction nothing commits, so nothing may be enqueued yet.
    post(client, payload("private_text_received"))

    assert enqueued == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {"event": "session.status", "data": {"status": "connected"}},
        "from_me_upsert",
    ],
)
def test_ignorable_payloads_are_200_and_store_nothing(
    client, payload, enqueued, django_capture_on_commit_callbacks, body
):
    if isinstance(body, str):
        body = payload(body)

    with django_capture_on_commit_callbacks(execute=True):
        response = post(client, body)

    assert response.status_code == 200
    assert InboundEvent.objects.count() == 0
    assert enqueued == []


@pytest.mark.django_db
def test_exact_path_without_trailing_slash_accepts_post(client, payload, fake_channel):
    response = post(client, payload("private_text_received"))

    assert response.status_code == 200
    assert response.request["PATH_INFO"] == URL


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fixture", "to"),
    [
        ("private_text_received", "237670000001"),
        ("private_text_personal", "237670000002"),
        ("flat_data_envelope", "237670000006"),
    ],
)
def test_new_user_gets_language_picker_at_sender(
    client, payload, fake_channel, django_capture_on_commit_callbacks, fixture, to
):
    with django_capture_on_commit_callbacks(execute=True):
        post(client, payload(fixture))

    assert fake_channel.sent == [{"type": "text", "to": to, "text": t("lang.picker", None)}]
    event = InboundEvent.objects.get()
    assert event.status == InboundEvent.Status.PROCESSED
    assert event.processed_at is not None


@pytest.mark.django_db
def test_group_message_goes_to_hook_not_routed(
    client, payload, fake_channel, monkeypatch, django_capture_on_commit_callbacks
):
    seen = []
    monkeypatch.setattr(hooks, "on_group_message", seen.append)

    with django_capture_on_commit_callbacks(execute=True):
        post(client, payload("group_text"))

    assert fake_channel.sent == []
    assert BotUser.objects.count() == 0
    assert [m.group_jid for m in seen] == ["120363000000000001@g.us"]
    assert InboundEvent.objects.get().status == InboundEvent.Status.PROCESSED


@pytest.mark.django_db
def test_private_media_from_new_user_is_not_echoed(
    client, payload, fake_channel, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        post(client, payload("image_caption"))

    assert [m["text"] for m in fake_channel.sent] == [t("lang.picker", None)]
    assert InboundEvent.objects.get().status == InboundEvent.Status.PROCESSED


@pytest.mark.django_db
def test_unstorable_payload_is_acknowledged_and_ignored(
    client, payload, enqueued, caplog, django_capture_on_commit_callbacks
):
    body = payload("private_text_received")
    body["data"]["messages"]["messageBody"] = "bad\u0000text"

    with django_capture_on_commit_callbacks(execute=True):
        response = post(client, body)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": True}
    assert InboundEvent.objects.count() == 0
    assert enqueued == []
    assert "DataError" in caplog.text
    assert "bad" not in caplog.text
