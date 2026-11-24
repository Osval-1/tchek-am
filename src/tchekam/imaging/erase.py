"""Deleting sightings, and the images (with thumbnails) nothing else still points to."""

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import ProtectedError, QuerySet

from tchekam.core.storage import get_object_store

from .models import Image, ImageSighting

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Erased:
    sightings: int
    images: int
    sha256s: list[str] = field(default_factory=list)  # of the deleted images


def delete_sightings(sightings: QuerySet[ImageSighting]) -> Erased:
    """Delete these sightings, then every image they leave without any sighting.

    An image is kept if another sighting remains or a report still refers to it (PROTECT).
    Thumbnails are removed from the ObjectStore only after the transaction commits, so a
    rollback never loses the blob of an image that is kept.

    Concurrent ingests: the affected images are row-locked first, so a sighting another
    transaction already committed is seen and keeps its image. A sighting committed after the
    lock fails its deferred foreign-key check instead of pointing at a deleted image.
    """
    with transaction.atomic():
        image_ids = sorted(set(sightings.values_list("image_id", flat=True)))
        if not image_ids:
            return Erased(0, 0)
        # Locked in pk order so two erasures never deadlock each other.
        list(Image.objects.select_for_update().filter(pk__in=image_ids).order_by("pk").values("pk"))
        count = ImageSighting.objects.filter(pk__in=sightings.values("pk")).delete()[0]
        deleted: list[Image] = []
        for image in Image.objects.filter(pk__in=image_ids, sightings__isnull=True).order_by("pk"):
            try:
                with transaction.atomic():
                    image.delete()
            except ProtectedError:
                continue  # a report still refers to it
            deleted.append(image)
        keys = [image.thumbnail_key for image in deleted if image.thumbnail_key]
        transaction.on_commit(lambda: _delete_blobs(keys))
    return Erased(count, len(deleted), [image.sha256 for image in deleted])


def _delete_blobs(keys: list[str]) -> None:
    store = get_object_store()
    for key in keys:
        try:
            store.delete(key)
        except Exception as exc:  # noqa: BLE001  the rows are gone; a stray blob is harmless
            logger.warning("imaging.erase: thumbnail not deleted: %s", type(exc).__name__)
