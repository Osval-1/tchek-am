import io
import logging

from PIL import Image as PILImage

from tchekam.conversations.models import BotUser
from tchekam.conversations.outbound import send_to_user
from tchekam.core import redact
from tchekam.core.storage import ObjectNotFoundError, get_object_store
from tchekam.core.tasks import register
from tchekam.i18n import t

from . import webcheck
from .embedder import get_embedder
from .models import Image

logger = logging.getLogger(__name__)


@register("imaging.embed")
def embed(image_id: int) -> None:
    """Compute and store the embedding of an image's thumbnail. Idempotent.

    Every image is embedded from its thumbnail so originals and copies are compared like for like.
    """
    image = Image.objects.filter(pk=image_id).first()
    if image is None or image.embedding is not None or not image.thumbnail_key:
        return
    try:
        data = get_object_store().get(image.thumbnail_key)
    except ObjectNotFoundError:
        logger.warning("imaging.embed: thumbnail missing for image %s", image_id)
        return
    with PILImage.open(io.BytesIO(data)) as thumb:
        vector = get_embedder().embed(thumb.convert("RGB"))
    Image.objects.filter(pk=image_id).update(embedding=vector)


MAX_FOLLOWUP_DOMAINS = 3
_FOLLOWUP_KINDS = ("catalogue", "marketplace")


@register("imaging.web_check")
def web_check(image_id: int, user_id: int) -> None:
    """Reverse-search a checked photo on the web; tell the user only if it is in a shop listing.

    Never raises: the user already has their answer, so a failure here must stay silent.
    """
    try:
        image = Image.objects.filter(pk=image_id).first()
        user = BotUser.objects.filter(pk=user_id).first()
        # Only the 256 px thumbnail is stored for submitted photos, so that is what is searched.
        if image is None or user is None or not image.thumbnail_key:
            return
        matches = webcheck.lookup(
            image.sha256, image.thumbnail_key, user=user, purpose=webcheck.SUBMISSION
        )
        domains = list(
            dict.fromkeys(m.source_domain for m in matches or [] if m.kind in _FOLLOWUP_KINDS)
        )
        if domains:
            text = t(
                "check.photo.online",
                user.language,
                domains=", ".join(domains[:MAX_FOLLOWUP_DOMAINS]),
            )
            send_to_user(user, text=text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("imaging.web_check: user %s: %s", redact(user_id), type(exc).__name__)
