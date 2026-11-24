import pytest

from tchekam.conversations.models import BotUser
from tchekam.identifiers.models import PhoneNumber
from tchekam.imaging.erase import delete_sightings
from tchekam.imaging.ingest import SightingContext, ingest
from tchekam.imaging.models import Image, ImageSighting
from tchekam.reports.models import Report, ReportSubject

from .helpers import encode, structured_image

pytestmark = pytest.mark.django_db


def _phone(e164):
    return PhoneNumber.objects.create(e164=e164, operator="mtn")


def _seen(seed, phone, context="group"):
    return ingest(
        encode(structured_image(seed)),
        "group",
        SightingContext(context=context, phone_number=phone),
    )


def test_deletes_sightings_and_orphaned_images_with_their_thumbnails(
    object_store, django_capture_on_commit_callbacks
):
    a = _phone("+237670000001")
    image = _seen(1, a)
    _seen(1, a)  # a second sighting of the same image by the same poster
    key = image.thumbnail_key
    assert object_store.exists(key)

    with django_capture_on_commit_callbacks(execute=True):
        erased = delete_sightings(ImageSighting.objects.filter(phone_number=a))

    assert (erased.sightings, erased.images) == (2, 1)
    assert erased.sha256s == [image.sha256]
    assert not Image.objects.exists()
    assert not object_store.exists(key)


def test_images_with_other_sightings_survive(object_store, django_capture_on_commit_callbacks):
    a, b = _phone("+237670000001"), _phone("+237670000002")
    shared = _seen(1, a)
    _seen(1, b)
    own = _seen(2, a)

    with django_capture_on_commit_callbacks(execute=True):
        erased = delete_sightings(ImageSighting.objects.filter(phone_number=a))

    assert (erased.sightings, erased.images) == (2, 1)
    assert list(Image.objects.all()) == [shared]
    assert list(ImageSighting.objects.values_list("phone_number", flat=True)) == [b.pk]
    assert object_store.exists(shared.thumbnail_key)
    assert not object_store.exists(own.thumbnail_key)


def test_images_a_report_refers_to_are_kept(object_store, django_capture_on_commit_callbacks):
    a = _phone("+237670000001")
    image = _seen(1, a)
    report = Report.objects.create(reporter=BotUser.objects.create(wa_phone="+237670000009"))
    ReportSubject.objects.create(report=report, role="product", source="user", image=image)

    with django_capture_on_commit_callbacks(execute=True):
        erased = delete_sightings(ImageSighting.objects.filter(phone_number=a))

    assert (erased.sightings, erased.images) == (1, 0)
    assert Image.objects.filter(pk=image.pk).exists()
    assert object_store.exists(image.thumbnail_key)


def test_thumbnails_are_only_deleted_after_commit(object_store):
    a = _phone("+237670000001")
    image = _seen(1, a)

    delete_sightings(ImageSighting.objects.filter(phone_number=a))

    # The test transaction never commits, so the blob must still be there.
    assert object_store.exists(image.thumbnail_key)


def test_nothing_to_delete():
    erased = delete_sightings(ImageSighting.objects.none())

    assert (erased.sightings, erased.images, erased.sha256s) == (0, 0, [])
