import io
import logging

from PIL import Image as PILImage

from tchekam.core.storage import ObjectNotFoundError, get_object_store
from tchekam.core.tasks import register

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
