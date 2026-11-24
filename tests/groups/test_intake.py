"""Group messages end to end, through the webhook (ADR-012)."""

import copy

import pytest

from tchekam.ai.models import AICallLog
from tchekam.ai.product_photo import PURPOSE
from tchekam.groups.models import GroupOptOut, PartnerGroup, UnconsentedGroupLeave
from tchekam.imaging.models import Image, ImageSighting
from tchekam.messaging.channel import ChannelError
from tchekam.messaging.models import InboundEvent

from ..imaging.helpers import encode, structured_image
from ..messaging.test_webhook import post
from .conftest import GROUP_JID, POSTER, load

pytestmark = pytest.mark.django_db

PRODUCT = '{"is_product": true}'
NOT_PRODUCT = '{"is_product": false}'


def group_image(message_id="MSG-GRP-IMG-1", **key):
    body = load("group_image_caption")
    body["data"]["messages"]["key"]["id"] = message_id
    body["data"]["messages"]["key"].update(key)
    return body


def group_text(message_id="MSG-GRP-1"):
    body = load("group_text")
    body["data"]["messages"]["key"]["id"] = message_id
    return body


@pytest.fixture
def deliver(client, django_capture_on_commit_callbacks):
    def send(body):
        with django_capture_on_commit_callbacks(execute=True):
            assert post(client, body).status_code == 200

    return send


@pytest.fixture
def seed(fake_channel):
    def seed_media(message_id="MSG-GRP-IMG-1", data=None):
        fake_channel.media[message_id] = (data or encode(structured_image(4)), "image/png")

    return seed_media


def leaves(fake_channel):
    return [s for s in fake_channel.sent if s["type"] == "leave_group"]


def assert_nothing_stored(object_store):
    assert not Image.objects.exists()
    assert not ImageSighting.objects.exists()
    assert object_store._objects == {}


def assert_never_sent_to_group(fake_channel):
    assert [s for s in fake_channel.sent if s["type"] != "leave_group"] == []


# --- groups without consent -------------------------------------------------------------


def test_unconsented_group_is_left_exactly_once(deliver, fake_channel, seed, object_store):
    seed()
    deliver(group_text())
    deliver(group_text())  # duplicate delivery
    deliver(group_text("MSG-GRP-2"))  # a later message
    deliver(group_image())

    assert leaves(fake_channel) == [{"type": "leave_group", "group_jid": GROUP_JID}]
    assert UnconsentedGroupLeave.objects.get().group_jid == GROUP_JID
    assert fake_channel.downloads == []
    assert_nothing_stored(object_store)
    assert_never_sent_to_group(fake_channel)


def test_failed_leave_is_not_recorded_so_the_next_message_retries(
    deliver, fake_channel, monkeypatch
):
    def broken(jid):
        raise ChannelError("WaSender groups: HTTP 500")

    monkeypatch.setattr(fake_channel, "leave_group", broken)
    deliver(group_text())

    assert not UnconsentedGroupLeave.objects.exists()
    assert InboundEvent.objects.get().status == InboundEvent.Status.FAILED

    monkeypatch.undo()
    deliver(group_text("MSG-GRP-2"))

    assert len(leaves(fake_channel)) == 1
    assert UnconsentedGroupLeave.objects.count() == 1


@pytest.mark.parametrize("status", [PartnerGroup.Status.PAUSED, PartnerGroup.Status.LEFT])
def test_paused_or_left_group_is_ignored_without_leaving(
    deliver, fake_channel, seed, make_partner_group, object_store, status
):
    make_partner_group(GROUP_JID, status=status)
    seed()

    deliver(group_image())

    assert leaves(fake_channel) == []
    assert fake_channel.downloads == []
    assert_nothing_stored(object_store)


# --- consented groups --------------------------------------------------------------------


def test_product_image_creates_image_and_group_sighting(
    deliver, fake_channel, fake_llm, seed, make_partner_group, object_store
):
    group = make_partner_group(GROUP_JID)
    seed()
    fake_llm.responses[PURPOSE] = [PRODUCT]

    deliver(group_image())

    image = Image.objects.get()
    assert image.source == Image.Source.GROUP
    assert object_store.exists(image.thumbnail_key)
    sighting = ImageSighting.objects.get()
    assert sighting.context == ImageSighting.Context.GROUP
    assert sighting.group == group
    assert sighting.phone_number.e164 == POSTER
    assert sighting.bot_user is None
    assert fake_channel.downloads == ["MSG-GRP-IMG-1"]
    assert leaves(fake_channel) == []
    assert_never_sent_to_group(fake_channel)


def test_non_product_image_stores_nothing(
    deliver, fake_channel, fake_llm, seed, make_partner_group, object_store
):
    make_partner_group(GROUP_JID)
    seed()
    fake_llm.responses[PURPOSE] = [NOT_PRODUCT]

    deliver(group_image())

    assert fake_channel.downloads == ["MSG-GRP-IMG-1"]
    assert_nothing_stored(object_store)
    assert_never_sent_to_group(fake_channel)


def test_classifier_failure_stores_nothing(
    deliver, fake_llm, seed, make_partner_group, object_store
):
    make_partner_group(GROUP_JID)
    seed()
    fake_llm.responses[PURPOSE] = [RuntimeError("down")]

    deliver(group_image())

    assert_nothing_stored(object_store)


def test_identical_image_is_classified_once(
    deliver, fake_llm, seed, make_partner_group, object_store
):
    make_partner_group(GROUP_JID)
    seed("A")
    seed("B")
    fake_llm.responses[PURPOSE] = [PRODUCT]

    deliver(group_image("A"))
    deliver(group_image("B"))

    assert len(fake_llm.calls) == 1
    assert AICallLog.objects.filter(purpose=PURPOSE).count() == 1
    assert Image.objects.count() == 1
    assert ImageSighting.objects.count() == 2


def test_unreadable_image_stores_nothing(
    deliver, fake_llm, seed, make_partner_group, object_store, monkeypatch
):
    make_partner_group(GROUP_JID)
    seed(data=b"not an image")
    # Even if the classifier said yes, ingest refuses the bytes and nothing is kept.
    monkeypatch.setattr("tchekam.groups.intake.is_product_photo", lambda data: True)

    deliver(group_image())

    assert_nothing_stored(object_store)
    assert InboundEvent.objects.get().status == InboundEvent.Status.PROCESSED


def test_failed_download_stores_nothing(deliver, fake_channel, make_partner_group, object_store):
    make_partner_group(GROUP_JID)  # no media seeded: the fake download raises ChannelError

    deliver(group_image())

    assert fake_channel.downloads == ["MSG-GRP-IMG-1"]
    assert_nothing_stored(object_store)


@pytest.mark.parametrize(
    "mutate",
    [
        {"conversation": "hello"},
        {"extendedTextMessage": {"text": "hello"}},
        {"audioMessage": {"url": "https://x", "mimetype": "audio/ogg"}},
        {"videoMessage": {"url": "https://x", "mimetype": "video/mp4"}},
        {"stickerMessage": {"url": "https://x", "mimetype": "image/webp"}},
        {"documentMessage": {"url": "https://x", "mimetype": "image/png"}},
        {"contactMessage": {"vcard": "BEGIN:VCARD\nTEL:+237690000000\nEND:VCARD"}},
    ],
)
def test_anything_but_an_image_is_ignored(
    deliver, fake_channel, fake_llm, make_partner_group, object_store, mutate
):
    make_partner_group(GROUP_JID)
    body = group_image()
    body["data"]["messages"]["message"] = mutate

    deliver(body)

    assert fake_channel.downloads == []
    assert fake_llm.calls == []
    assert_nothing_stored(object_store)
    assert_never_sent_to_group(fake_channel)


@pytest.mark.parametrize(
    "key",
    [
        {"cleanedParticipantPn": None},  # LID only: the poster's number is unknown
        {"cleanedParticipantPn": "33612345678"},  # not a Cameroonian number
    ],
)
def test_images_without_a_usable_poster_number_are_not_downloaded(
    deliver, fake_channel, seed, make_partner_group, object_store, key
):
    make_partner_group(GROUP_JID)
    seed()
    body = group_image()
    keys = body["data"]["messages"]["key"]
    for name, value in key.items():
        if value is None:
            keys.pop(name)
        else:
            keys[name] = value

    deliver(body)

    assert fake_channel.downloads == []
    assert_nothing_stored(object_store)


def test_images_from_opted_out_posters_are_not_downloaded(
    deliver, fake_channel, fake_llm, seed, make_partner_group, object_store
):
    make_partner_group(GROUP_JID)
    GroupOptOut.objects.create(wa_phone=POSTER)
    seed()
    fake_llm.responses[PURPOSE] = [PRODUCT]

    deliver(group_image())

    assert fake_channel.downloads == []
    assert fake_llm.calls == []
    assert_nothing_stored(object_store)


def test_opt_out_between_queueing_and_ingest_still_wins(
    fake_channel, fake_llm, seed, make_partner_group, object_store, monkeypatch
):
    """The job re-checks the opt-out under the poster lock right before storing."""
    from tchekam.groups import intake

    make_partner_group(GROUP_JID)
    seed()
    body = copy.deepcopy(group_image())
    InboundEvent.objects.create(message_id="MSG-GRP-IMG-1", event="x", payload=body)

    def classify_then_opt_out(data):
        GroupOptOut.objects.create(wa_phone=POSTER)
        return True

    monkeypatch.setattr(intake, "is_product_photo", classify_then_opt_out)
    intake.ingest_group_image(message_id="MSG-GRP-IMG-1")

    assert_nothing_stored(object_store)


def test_job_for_a_missing_or_private_event_does_nothing(fake_channel):
    from tchekam.groups import intake

    intake.ingest_group_image(message_id="nope")
    InboundEvent.objects.create(message_id="MSG-IMG-1", event="x", payload=load("image_caption"))
    intake.ingest_group_image(message_id="MSG-IMG-1")

    assert fake_channel.downloads == []
