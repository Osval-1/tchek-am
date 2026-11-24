import threading
import time

import pytest
from django.db import connection, transaction

from tchekam.ai.product_photo import PURPOSE
from tchekam.conversations.models import BotUser
from tchekam.conversations.service import handle_private_message
from tchekam.core.models import AuditLog
from tchekam.groups.models import GroupOptOut
from tchekam.groups.optout import lock_poster, opt_out
from tchekam.i18n import t
from tchekam.identifiers.models import get_or_create_phone
from tchekam.imaging.ingest import SightingContext, ingest
from tchekam.imaging.models import Image, ImageSighting
from tchekam.messaging.channel import InboundMessage

from ..imaging.helpers import encode, structured_image
from ..messaging.test_webhook import post
from .conftest import GROUP_JID, POSTER, load

OTHER = "+237670000004"


def private(text, phone=POSTER):
    return InboundMessage(
        message_id=f"P-{text}",
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


def say(text, phone=POSTER):
    return "\n".join(r.text for r in handle_private_message(private(text, phone)))


def group_sighting(seed, phone, group):
    ctx = SightingContext(context="group", phone_number=get_or_create_phone(phone), group=group)
    return ingest(encode(structured_image(seed)), "group", ctx)


@pytest.fixture
def onboarded(db):
    return BotUser.objects.create(wa_phone=POSTER, language="en")


@pytest.mark.django_db
@pytest.mark.parametrize("text", ["STOP GROUP", "stop groupe", "  Stop-Group!! ", "stop  GROUPE."])
def test_stop_group_deletes_sightings_orphans_and_thumbnails(
    onboarded, make_partner_group, object_store, django_capture_on_commit_callbacks, text
):
    group = make_partner_group(GROUP_JID)
    own = group_sighting(1, POSTER, group)
    group_sighting(1, POSTER, group)
    shared = group_sighting(2, POSTER, group)
    group_sighting(2, OTHER, group)
    submitted = ingest(
        encode(structured_image(3)), "submission", SightingContext("submission", bot_user=onboarded)
    )

    with django_capture_on_commit_callbacks(execute=True):
        reply = say(text)

    assert reply == t("groups.opt_out.done", "en")
    assert GroupOptOut.objects.filter(wa_phone=POSTER).exists()
    assert set(Image.objects.all()) == {shared, submitted}
    assert not object_store.exists(own.thumbnail_key)
    assert object_store.exists(shared.thumbnail_key)
    remaining = ImageSighting.objects.all()
    assert {(s.context, s.phone_number and s.phone_number.e164) for s in remaining} == {
        ("group", OTHER),
        ("submission", None),
    }


@pytest.mark.django_db
def test_opt_out_is_audited_with_counts_only(onboarded, make_partner_group):
    group = make_partner_group(GROUP_JID)
    group_sighting(1, POSTER, group)

    say("STOP GROUP")

    entry = AuditLog.objects.get(action="groups.opt_out")
    assert entry.metadata == {"sightings": 1, "images": 1}
    assert (entry.object_type, entry.object_id) == ("conversations.botuser", str(onboarded.pk))
    assert POSTER.lstrip("+") not in str(entry.metadata)


@pytest.mark.django_db
def test_nothing_to_delete_still_records_the_opt_out(onboarded):
    assert say("STOP GROUP") == t("groups.opt_out.nothing", "en")
    assert say("STOP GROUP") == t("groups.opt_out.nothing", "en")  # idempotent

    assert GroupOptOut.objects.count() == 1


@pytest.mark.django_db
def test_stop_group_works_before_onboarding_and_answers_in_all_languages(make_partner_group):
    group_sighting(1, POSTER, make_partner_group(GROUP_JID))

    reply = say("stop group")

    for lang in ("fr", "en", "pcm"):
        assert t("groups.opt_out.done", lang) in reply
    assert not ImageSighting.objects.exists()
    assert BotUser.objects.get(wa_phone=POSTER).language is None
    # The next message still starts onboarding.
    assert say("hello") == t("lang.picker", None)


@pytest.mark.django_db
def test_later_group_images_from_that_number_are_not_downloaded(
    client, onboarded, make_partner_group, fake_channel, fake_llm, object_store,
    django_capture_on_commit_callbacks,
):  # fmt: skip
    make_partner_group(GROUP_JID)
    say("STOP GROUP")
    fake_channel.media["MSG-GRP-IMG-1"] = (encode(structured_image(4)), "image/png")
    fake_llm.responses[PURPOSE] = ['{"is_product": true}']

    with django_capture_on_commit_callbacks(execute=True):
        post(client, load("group_image_caption"))

    assert fake_channel.downloads == []
    assert not Image.objects.exists()


@pytest.mark.django_db
def test_confirmation_copy_never_uses_banned_words():
    from ..i18n.test_catalog import BANNED_RE

    for key in ("groups.opt_out.done", "groups.opt_out.nothing"):
        for lang in ("fr", "en", "pcm"):
            assert not BANNED_RE.search(t(key, lang))


@pytest.mark.django_db(transaction=True)
def test_opt_out_waits_for_an_in_flight_ingest_and_deletes_its_sighting(
    make_partner_group, object_store
):
    """An ingest holding the poster lock commits first; the opt-out then deletes its work."""
    group = make_partner_group(GROUP_JID)
    user = BotUser.objects.create(wa_phone=POSTER, language="en")
    locked = threading.Event()

    def ingest_slowly():
        try:
            with transaction.atomic():
                lock_poster(POSTER)
                locked.set()
                group_sighting(1, POSTER, group)
                time.sleep(0.3)
        finally:
            connection.close()

    worker = threading.Thread(target=ingest_slowly)
    worker.start()
    assert locked.wait(5)
    erased = opt_out(user)
    worker.join()

    assert (erased.sightings, erased.images) == (1, 1)
    assert not ImageSighting.objects.exists()
    assert not Image.objects.exists()


@pytest.mark.django_db
def test_blocked_user_can_still_opt_out(make_partner_group, object_store):
    BotUser.objects.create(wa_phone=POSTER, language="en", blocked=True)
    group_sighting(1, POSTER, make_partner_group(GROUP_JID))

    reply = say("STOP GROUP")

    assert reply == t("groups.opt_out.done", "en")
    assert not ImageSighting.objects.exists()
    assert not Image.objects.exists()
    assert GroupOptOut.objects.filter(wa_phone=POSTER).exists()


@pytest.mark.django_db
# STOP TRAINING is a data-protection command too (tests/retention/test_training.py).
@pytest.mark.parametrize("text", ["menu", "LANG", "4", "677123456", "hello"])
def test_blocked_user_gets_nothing_for_anything_else(fake_channel, text):
    user = BotUser.objects.create(wa_phone=POSTER, language="en", blocked=True)

    assert say(text) == ""
    assert user.conversation.flow == "idle"
    assert not GroupOptOut.objects.exists()
