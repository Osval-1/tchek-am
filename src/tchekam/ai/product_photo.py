"""Product-photo classifier for group listening (F8): is this a photo of something for sale?

Only a "yes" lets a partner-group image into the photo database; anything else is discarded.
"""

import hashlib
import logging
from collections.abc import Iterable

from django.conf import settings
from django.core.cache import cache

from .client import INVALID_OUTPUT, get_llm_client
from .extraction import image_block
from .registry import get_prompt
from .schemas import ProductPhoto

logger = logging.getLogger(__name__)

PURPOSE = "is_product_photo"
EFFORT = "low"
MAX_TOKENS = 1024
# The shared DatabaseCache in prod. Keyed by prompt version, so a new prompt reclassifies.
CACHE_SECONDS = 30 * 24 * 3600
_USER_TEXT = "Classify this photo. Return is_product."


def _cache_key(sha256: str, version: str) -> str:
    return f"ai:{PURPOSE}:{version}:{sha256}"


def is_product_photo(data: bytes) -> bool | None:
    """True or False from the model, cached per sha256 of the bytes. Never raises.

    None means "could not tell" (unreadable image, provider failure, refusal); callers treat
    it as not a product. Failures are not cached, so the same image is retried next time.
    """
    system, version = get_prompt(PURPOSE)
    key = _cache_key(hashlib.sha256(data).hexdigest(), version)
    cached = cache.get(key)
    if cached is not None:
        return cached
    block = image_block(data)
    if block is None:
        return None
    client = get_llm_client()
    for _attempt in range(2):  # one retry, and only for output that failed validation
        result = client.structured(
            purpose=PURPOSE,
            model=settings.AI_MODEL_FAST,
            system=system,
            user_content=[block, {"type": "text", "text": _USER_TEXT}],
            schema_model=ProductPhoto,
            effort=EFFORT,
            max_tokens=MAX_TOKENS,
            prompt_version=version,
            use_fallback=False,  # Haiku has no server-side fallback
        )
        if result.ok:
            verdict = result.data.is_product
            cache.set(key, verdict, CACHE_SECONDS)
            return verdict
        if result.error != INVALID_OUTPUT:
            break
    return None


def forget(sha256s: Iterable[str]) -> None:
    """Drop cached verdicts, e.g. for images erased on a poster's opt-out."""
    _, version = get_prompt(PURPOSE)
    keys = [_cache_key(sha, version) for sha in sha256s]
    if keys:
        cache.delete_many(keys)
