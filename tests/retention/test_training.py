"""Training copies of voice notes (ADR-013): made at decision time, deleted on STOP TRAINING."""

import pytest
from django.contrib.auth import get_user_model

from tchekam.conversations.models import Conversation
from tchekam.conversations.service import handle_private_message
from tchekam.i18n import t
from tchekam.messaging.channel import InboundMessage
from tchekam.reports.models import Evidence
from tchekam.retention import training
from tchekam.retention.models import TrainingSample

from .builders import evidence, report, user

pytestmark = pytest.mark.django_db


def _voice_report(opted_in=True, status="pending"):
    owner = user(training_opt_in=opted_in, training_opt_in_asked=True)
    r = report(status, owner)
    voice = evidence(r, Evidence.Kind.VOICE, training_opt_in=opted_in)
    return r, voice


@pytest.fixture
def mod():
    return get_user_model().objects.create_user("mod")


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_decision_copies_opted_in_voice_notes_to_the_training_prefix(
    object_store, django_capture_on_commit_callbacks, mod, decision
):
    r, voice = _voice_report()

    with django_capture_on_commit_callbacks(execute=True):
        r.transition(decision, actor=mod)

    sample = TrainingSample.objects.get()
    assert sample.audio_key.startswith("training/")
    assert sample.audio_key != voice.object_key
    assert object_store.get(sample.audio_key) == object_store.get(voice.object_key)
    assert sample.user == r.reporter and sample.evidence == voice
    assert sample.transcript == voice.transcript and sample.corrected_transcript == ""


def test_no_copy_without_opt_in(django_capture_on_commit_callbacks, mod):
    r, _ = _voice_report(opted_in=False)

    with django_capture_on_commit_callbacks(execute=True):
        r.transition("approved", actor=mod)

    assert not TrainingSample.objects.exists()


def test_no_copy_once_the_user_withdrew(django_capture_on_commit_callbacks, mod):
    r, _ = _voice_report()
    type(r.reporter).objects.filter(pk=r.reporter_id).update(training_opt_in=False)

    with django_capture_on_commit_callbacks(execute=True):
        r.transition("approved", actor=mod)

    assert not TrainingSample.objects.exists()


def test_copy_is_idempotent(object_store):
    r, _ = _voice_report(status="approved")

    assert training.copy_samples(r.pk) == 1
    assert training.copy_samples(r.pk) == 0
    assert TrainingSample.objects.count() == 1
    assert len([k for k in object_store._objects if k.startswith("training/")]) == 1


def test_samples_outlive_the_report_evidence(object_store):
    from datetime import timedelta

    from tchekam.retention import rules

    from .builders import NOW

    r, voice = _voice_report(status="approved")
    training.copy_samples(r.pk)
    type(r).objects.filter(pk=r.pk).update(decided_at=NOW - timedelta(days=4 * 365))

    rules.approved_evidence(NOW)

    sample = TrainingSample.objects.get()
    assert sample.evidence is None
    assert object_store.exists(sample.audio_key)


def _msg(phone, text):
    return InboundMessage(
        message_id=f"M-{text}-{phone}",
        sender_phone=phone.lstrip("+"),
        sender_jid=None,
        chat_type="private",
        group_jid=None,
        kind="text",
        text=text,
        media=None,
        timestamp=1,
        raw_event="messages.received",
    )


def test_stop_training_deletes_all_the_users_samples(
    object_store, django_capture_on_commit_callbacks
):
    r, voice = _voice_report(status="approved")
    training.copy_samples(r.pk)
    key = TrainingSample.objects.get().audio_key
    other, _ = _voice_report(status="approved")
    training.copy_samples(other.pk)
    owner = r.reporter
    Conversation.objects.create(user=owner)

    with django_capture_on_commit_callbacks(execute=True):
        replies = handle_private_message(_msg(owner.wa_phone, "STOP TRAINING"))

    assert replies[0].text == t("training.opt_out.done", "en")
    assert not TrainingSample.objects.filter(user=owner).exists()
    assert not object_store.exists(key)
    assert TrainingSample.objects.filter(user=other.reporter).count() == 1
    owner.refresh_from_db()
    assert owner.training_opt_in is False and owner.training_opt_in_asked is True
    voice.refresh_from_db()
    assert voice.training_opt_in is False


def test_stop_training_blob_deletion_is_queued_not_run_under_the_lock(monkeypatch):
    owner = user(training_opt_in=True)
    queued = []
    monkeypatch.setattr(
        "tchekam.conversations.service.enqueue", lambda name, **kw: queued.append((name, kw))
    )

    handle_private_message(_msg(owner.wa_phone, "stop training"))

    assert queued == [("retention.delete_training_samples", {"user_id": owner.pk})]


def test_stop_training_works_before_onboarding_and_for_blocked_users():
    blocked = user(language=None, blocked=True, training_opt_in=True)

    replies = handle_private_message(_msg(blocked.wa_phone, "Stop Training"))

    text = replies[0].text
    assert all(t("training.opt_out.done", lang) in text for lang in ("fr", "en", "pcm"))
    blocked.refresh_from_db()
    assert blocked.training_opt_in is False


def test_held_users_samples_survive_stop_training(object_store):
    r, _ = _voice_report(status="approved")
    training.copy_samples(r.pk)
    type(r.reporter).objects.filter(pk=r.reporter_id).update(legal_hold=True)

    assert training.delete_samples(r.reporter_id) == 0
    assert TrainingSample.objects.exists()
