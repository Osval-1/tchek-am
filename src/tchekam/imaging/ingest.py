"""Turning image bytes into an Image row plus a sighting."""

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction

from tchekam.conversations.models import BotUser
from tchekam.core import tasks
from tchekam.core.storage import get_object_store, new_key
from tchekam.identifiers.models import PhoneNumber

from . import hashing
from .models import Image, ImageSighting

if TYPE_CHECKING:  # imaging only stores the reference; it never depends on groups behaviour
    from tchekam.groups.models import PartnerGroup


@dataclass(frozen=True)
class SightingContext:
    """Where an image was seen."""

    context: str
    phone_number: PhoneNumber | None = None
    bot_user: BotUser | None = None
    group: "PartnerGroup | None" = None


def ingest(data: bytes, source: str, sighting_ctx: SightingContext) -> Image:
    """Return the Image for these bytes (creating it if new) and record the sighting.

    Raises hashing.ImageRejected for bytes that are not a safe, supported image.
    """
    sha = hashlib.sha256(data).hexdigest()
    image = Image.objects.filter(sha256=sha).first()
    if image is None:
        image = _create(data, sha, source)
    _record(image, sighting_ctx)
    return image


def _create(data: bytes, sha: str, source: str) -> Image:
    decoded = hashing.decode(data)
    phash = hashing.phash(decoded)
    store = get_object_store()
    key = store.put(new_key("thumbnails"), hashing.thumbnail_jpeg(decoded), "image/jpeg")
    try:
        with transaction.atomic():
            image = Image.objects.create(
                sha256=sha,
                phash=phash,
                dhash=hashing.dhash(decoded),
                phash_bands=hashing.bands(phash),
                thumbnail_key=key,
                width=decoded.width,
                height=decoded.height,
                source=source,
            )
    except IntegrityError:
        # Lost a race with a concurrent ingest of the same bytes: use theirs, drop our blob.
        store.delete(key)
        return Image.objects.get(sha256=sha)
    # After commit, so a worker never looks for an image the caller's transaction has not saved.
    transaction.on_commit(lambda: tasks.enqueue("imaging.embed", image_id=image.pk))
    return image


def _record(image: Image, ctx: SightingContext) -> None:
    ImageSighting.objects.create(
        image=image,
        phone_number=ctx.phone_number,
        bot_user=ctx.bot_user,
        group=ctx.group,
        context=ctx.context,
    )
