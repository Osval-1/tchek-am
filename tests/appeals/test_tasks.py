import pytest

from tchekam.appeals import tasks
from tchekam.appeals.models import Appeal, AppealEvidence
from tchekam.identifiers.models import get_or_create_phone

from .conftest import OWN

pytestmark = pytest.mark.django_db


def draft(user, status="draft"):
    return Appeal.objects.create(
        phone_number=get_or_create_phone(OWN), appellant=user, kind="wrong", status=status
    )


def test_ingest_skips_appeals_that_are_no_longer_drafts(bot, fake_channel, object_store):
    appeal = draft(bot.user, "open")
    tasks.ingest_media(appeal.pk, "unknown-message", "image")
    tasks.ingest_media(999999, "x", "image")
    assert not AppealEvidence.objects.exists() and fake_channel.downloads == []


def test_ingest_ignores_unknown_messages_silently(bot, fake_channel):
    appeal = draft(bot.user)
    tasks.ingest_media(appeal.pk, "never-received", "image")
    assert not AppealEvidence.objects.exists()
    assert [m["text"] for m in fake_channel.sent] == [
        "I could not get that file. Send it again, or send DONE to continue without it."
    ]


def test_discard_only_removes_drafts(bot, object_store):
    keep = draft(bot.user, "open")
    gone = draft(bot.user)
    object_store.put("appeal-evidence/z", b"x", "image/png")
    AppealEvidence.objects.create(
        appeal=gone, object_key="appeal-evidence/z", mimetype="image/png",
        sha256="b" * 64, size_bytes=1, source_message_id="m",
    )  # fmt: skip
    tasks.discard_draft(keep.pk)
    tasks.discard_draft(gone.pk)
    tasks.discard_draft(gone.pk)
    assert Appeal.objects.filter(pk=keep.pk).exists()
    assert not Appeal.objects.filter(pk=gone.pk).exists()
    assert not object_store.exists("appeal-evidence/z")
