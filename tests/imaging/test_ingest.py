import pytest
from PIL import Image as PILImage

from tchekam.conversations.models import BotUser
from tchekam.identifiers.models import PhoneNumber
from tchekam.imaging import hashing
from tchekam.imaging.ingest import SightingContext, ingest
from tchekam.imaging.models import Image, ImageSighting

from .helpers import encode, structured_image

pytestmark = pytest.mark.django_db

SUBMISSION = SightingContext(context="submission")


def test_ingest_same_bytes_twice_gives_one_image_and_two_sightings(
    object_store, django_capture_on_commit_callbacks
):
    data = encode(structured_image(1))
    with django_capture_on_commit_callbacks(execute=True):
        first = ingest(data, "submission", SUBMISSION)
        second = ingest(data, "submission", SUBMISSION)

    assert first.pk == second.pk
    assert Image.objects.count() == 1
    assert ImageSighting.objects.filter(image=first).count() == 2
    assert len(object_store._objects) == 1  # the thumbnail was stored once


def test_ingest_stores_hashes_dimensions_and_thumbnail(object_store):
    img = structured_image(1, size=300)
    image = ingest(encode(img), "catalogue", SUBMISSION)
    image.refresh_from_db()

    assert (image.width, image.height, image.source) == (300, 300, "catalogue")
    assert image.phash == hashing.phash(img)
    assert image.dhash == hashing.dhash(img)
    assert image.phash_bands == hashing.bands(image.phash)
    assert image.thumbnail_key.startswith("thumbnails/")
    thumb = PILImage.open(__import__("io").BytesIO(object_store.get(image.thumbnail_key)))
    assert thumb.format == "JPEG" and max(thumb.size) == 256


def test_ingest_enqueues_embedding_which_runs_eagerly(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        image = ingest(encode(structured_image(1)), "submission", SUBMISSION)
    image.refresh_from_db()
    assert image.embedding is not None
    assert len(image.embedding) == 512


def test_embed_task_is_idempotent_and_tolerates_missing_image(object_store):
    from tchekam.imaging.tasks import embed

    embed(image_id=999999)
    image = ingest(encode(structured_image(1)), "submission", SUBMISSION)
    embed(image_id=image.pk)
    first = list(Image.objects.get(pk=image.pk).embedding)
    embed(image_id=image.pk)
    assert list(Image.objects.get(pk=image.pk).embedding) == first
    object_store.reset()
    other = Image.objects.create(sha256="x" * 64, thumbnail_key="thumbnails/gone")
    embed(image_id=other.pk)  # thumbnail missing: no crash, no embedding
    other.refresh_from_db()
    assert other.embedding is None


def test_sighting_records_phone_user_and_group_placeholder():
    phone = PhoneNumber.objects.create(e164="+237670000001", operator="mtn")
    user = BotUser.objects.create(wa_phone="237670000002")
    ctx = SightingContext(context="group", phone_number=phone, bot_user=user, group_id=5)
    image = ingest(encode(structured_image(1)), "group", ctx)
    sighting = image.sightings.get()
    assert (sighting.phone_number, sighting.bot_user, sighting.group_id) == (phone, user, 5)


@pytest.mark.parametrize("bad", [b"", b"garbage", encode(PILImage.new("RGB", (8, 8)), "BMP")])
def test_bad_images_are_rejected_and_leave_nothing_behind(bad, object_store):
    with pytest.raises(hashing.ImageRejected):
        ingest(bad, "submission", SUBMISSION)
    assert Image.objects.count() == 0 and ImageSighting.objects.count() == 0
    assert object_store._objects == {}


def test_oversized_image_is_rejected(monkeypatch):
    monkeypatch.setattr(hashing, "MAX_IMAGE_BYTES", 50)
    with pytest.raises(hashing.ImageRejected):
        ingest(encode(structured_image(1)), "submission", SUBMISSION)


def test_race_lost_to_a_concurrent_ingest_reuses_their_image(object_store, monkeypatch):
    data = encode(structured_image(1))
    existing = ingest(data, "submission", SUBMISSION)
    store_size = len(object_store._objects)
    # Simulate the lookup missing a row that another worker committed a moment earlier.
    from tchekam.imaging import ingest as ingest_module

    image = ingest_module._create(data, existing.sha256, "submission")
    assert image.pk == existing.pk
    assert len(object_store._objects) == store_size  # our orphan thumbnail was deleted
