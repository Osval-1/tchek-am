"""Evidence extraction: screenshots, transcripts and story -> a validated Extraction."""

import base64
import io
import logging
import re
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from PIL import Image

from tchekam.identifiers.names import normalize_name
from tchekam.identifiers.phone import normalize_cm_number

from .client import INVALID_OUTPUT, get_llm_client
from .registry import get_prompt
from .schemas import Extraction

logger = logging.getLogger(__name__)

PURPOSE = "evidence_extraction"
# Formats the API accepts as is; anything else Pillow can read is re-encoded.
NATIVE_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
# Declared types that are clearly not images. The declared type is otherwise ignored.
_NON_IMAGE_PREFIXES = ("audio/", "video/", "text/", "application/")
_OPAQUE_LABELS = frozenset({"application/octet-stream"})
MAX_IMAGES = 10
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_SIDE = 1568
# The API rejects any side over 8000 px. Tall chat screenshots are shrunk only to this, not to
# MAX_SIDE, so their text stays legible.
MAX_SIDE_SENT = 7500
# Our own decompression-bomb cap, checked from the header before any pixel is decoded.
MAX_PIXELS = 40_000_000
EFFORT = "medium"
MAX_TOKENS = 4096
_LANGUAGES = {"fr": "French", "en": "English", "pcm": "Cameroonian Pidgin English"}
_TZ = ZoneInfo("Africa/Douala")
# R4: no accusatory labels in AI text a reporter or moderator reads (FR/EN/Pidgin).
_ACCUSATORY = re.compile(
    r"\b(?:scammers?|scam\s+artists?|fraudsters?|frauds?|fraudeurs?|fraudeuses?|fraudes?"
    r"|arnaqueurs?|arnaqueuses?|escrocs?|voleurs?|voleuses?|feymans?|thief|thieves)\b",
    re.IGNORECASE,
)


def extract_evidence(
    images: list[tuple[bytes, str]], transcript: str | None, story: str | None, lang: str
) -> Extraction:
    """Extract structured details from report evidence. Never raises for model failures.

    `images` are (bytes, mimetype) pairs. The media type sent is detected from the bytes;
    the declared mimetype only screens out non-image media. Images that cannot be sent
    (non-image type, unreadable, over the pixel cap, beyond the first MAX_IMAGES) are skipped, but
    `evidence_kinds` still has one entry per input image ("other" for skipped ones). Never raises
    for any image input. On failure, returns an empty Extraction with extraction_failed=True.
    """
    sent_slots, blocks = _image_blocks(images)
    blocks.append({"type": "text", "text": _user_text(len(sent_slots), transcript, story, lang)})
    system, version = get_prompt(PURPOSE)
    client = get_llm_client()

    for _attempt in range(2):  # one retry, and only for output that failed validation
        result = client.structured(
            purpose=PURPOSE,
            model=settings.AI_MODEL_VISION,
            system=system,
            user_content=blocks,
            schema_model=Extraction,
            effort=EFFORT,
            max_tokens=MAX_TOKENS,
            prompt_version=version,
            use_fallback=settings.AI_REFUSAL_FALLBACK,
        )
        if result.ok:
            return _clean(result.data, sent_slots, len(images))
        if result.error != INVALID_OUTPUT:
            break
    return Extraction.failed(len(images))


def _image_blocks(images: list[tuple[bytes, str]]) -> tuple[list[int], list[dict]]:
    """Content blocks for the sendable images, and the input index of each one sent."""
    slots: list[int] = []
    blocks: list[dict] = []
    for index, (data, mimetype) in enumerate(images):
        if len(slots) == MAX_IMAGES:
            logger.info("extraction: image cap reached, %d image(s) not sent", len(images) - index)
            break
        if mimetype.startswith(_NON_IMAGE_PREFIXES) and mimetype not in _OPAQUE_LABELS:
            logger.info("extraction: skipping non-image media of type %s", mimetype)
            continue
        prepared = _prepare(data)
        if prepared is None:
            continue
        data, mimetype = prepared
        slots.append(index)
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mimetype,
                    "data": base64.standard_b64encode(data).decode("ascii"),
                },
            }
        )
    return slots, blocks


def _prepare(data: bytes) -> tuple[bytes, str] | None:
    """(bytes, media type) to send, or None to skip the image (unreadable or a decompression bomb).

    Image.open only parses the header, so the pixel cap is checked before anything is decoded.
    JPEG, PNG and WebP up to MAX_IMAGE_BYTES are sent unchanged, typed by their detected format.
    Other formats (GIF, BMP, TIFF, ...) are re-encoded. Anything over MAX_IMAGE_BYTES is
    downscaled to MAX_SIDE; otherwise a side over MAX_SIDE_SENT is downscaled to MAX_SIDE_SENT.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            width, height = image.size
            if width * height > MAX_PIXELS:
                logger.info("extraction: skipping image over the pixel cap")
                return None
            too_long = max(width, height) > MAX_SIDE_SENT
            native = NATIVE_FORMATS.get(image.format or "")
            if native and len(data) <= MAX_IMAGE_BYTES and not too_long:
                return data, native
            if len(data) > MAX_IMAGE_BYTES:
                image.thumbnail((MAX_SIDE, MAX_SIDE))
            elif too_long:
                image.thumbnail((MAX_SIDE_SENT, MAX_SIDE_SENT))
            encoded = _encode(image)
            if len(encoded[0]) > MAX_IMAGE_BYTES:  # a small file can decode to a large one
                image.thumbnail((MAX_SIDE, MAX_SIDE))
                encoded = _encode(image)
            return encoded
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        logger.info("extraction: skipping image over Pillow's decompression-bomb limit")
        return None
    except Exception:  # untrusted bytes: Pillow raises many types (OSError, SyntaxError, ...)
        logger.info("extraction: skipping unreadable image")
        return None


def _encode(image: Image.Image) -> tuple[bytes, str]:
    """PNG when the image has transparency (JPEG would flatten it badly), else JPEG."""
    out = io.BytesIO()
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        image.convert("RGBA").save(out, format="PNG", optimize=True)
        return out.getvalue(), "image/png"
    image.convert("RGB").save(out, format="JPEG", quality=85)
    return out.getvalue(), "image/jpeg"


def _user_text(image_count: int, transcript: str | None, story: str | None, lang: str) -> str:
    # Volatile values live here, not in the system prompt, so the system prompt stays cacheable.
    today = datetime.now(_TZ).date().isoformat()
    parts = [
        f"Reporter's language for the summary: {_LANGUAGES.get(lang, 'French')}.",
        f"Today's date (Africa/Douala): {today}.",
        f"Number of images: {image_count}. Return exactly {image_count} evidence_kinds.",
    ]
    if transcript:
        parts.append(f"<transcript>\n{transcript}\n</transcript>")
    if story:
        parts.append(f"<story>\n{story}\n</story>")
    if not transcript and not story:
        parts.append("No transcript or story was provided.")
    return "\n\n".join(parts)


def _clean(raw: Extraction, sent_slots: list[int], image_count: int) -> Extraction:
    phones = [n for n in (normalize_cm_number(p) for p in raw.phone_numbers) if n]
    names = {}
    for item in raw.account_names:
        name = " ".join(item.name.split())
        if name:
            names.setdefault(normalize_name(name), item.model_copy(update={"name": name}))
    kinds = ["other"] * image_count
    for slot, kind in zip(sent_slots, raw.evidence_kinds, strict=False):
        kinds[slot] = kind
    summary_filtered = bool(_ACCUSATORY.search(raw.summary))
    return raw.model_copy(
        update={
            "summary": "" if summary_filtered else raw.summary,
            "summary_filtered": summary_filtered,
            "tamper_observations": [
                t for t in raw.tamper_observations if not _ACCUSATORY.search(t)
            ],
            "phone_numbers": list(dict.fromkeys(phones)),
            "account_names": list(names.values()),
            "amounts_xaf": [a for a in raw.amounts_xaf if a > 0],
            "evidence_kinds": kinds,
            "extraction_failed": False,
        }
    )
