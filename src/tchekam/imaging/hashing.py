"""Safe decoding, perceptual hashes, pHash bucket keys and thumbnails. No database access."""

import io
import warnings

import imagehash
from PIL import Image as PILImage
from PIL import ImageOps

# One set of limits for every place we decode untrusted images.
from tchekam.ai.extraction import MAX_IMAGE_BYTES, MAX_PIXELS

ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})
THUMBNAIL_SIDE = 256
MAX_PHASH_DISTANCE = 8
# 9 bands cover 64 bits (eight of 7 bits, one of 8). Two hashes at Hamming distance <= 8 differ
# in at most 8 bits, so they touch at most 8 bands and by pigeonhole at least one of the 9 bands
# is identical. Matching on any identical band therefore never misses a distance <= 8 pair.
BAND_WIDTHS = (7, 7, 7, 7, 7, 7, 7, 7, 8)
assert sum(BAND_WIDTHS) == 64 and len(BAND_WIDTHS) == MAX_PHASH_DISTANCE + 1


class ImageRejected(ValueError):
    """The bytes are not an image we are willing to process."""


def to_signed(value: int) -> int:
    """Unsigned 64-bit -> signed, because Postgres bigint is signed. Lossless and bit-exact."""
    return value - (1 << 64) if value >= 1 << 63 else value


def to_unsigned(value: int) -> int:
    return value + (1 << 64) if value < 0 else value


def decode(data: bytes) -> PILImage.Image:
    """Decode untrusted bytes to an upright RGB image, or raise ImageRejected.

    The pixel cap is checked from the header before anything is decoded.
    """
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageRejected("empty or over the size cap")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PILImage.DecompressionBombWarning)
            image = PILImage.open(io.BytesIO(data))
            if image.format not in ALLOWED_FORMATS:
                raise ImageRejected(f"unsupported format {image.format}")
            if image.width * image.height > MAX_PIXELS:
                raise ImageRejected("over the pixel cap")
            image.load()
            return ImageOps.exif_transpose(image).convert("RGB")
    except ImageRejected:
        raise
    except Exception as exc:  # untrusted bytes: Pillow raises many types, bombs included
        raise ImageRejected("unreadable image") from exc


def _bits(h: imagehash.ImageHash) -> int:
    return int("".join("1" if b else "0" for b in h.hash.flatten()), 2)


def phash(image: PILImage.Image) -> int:
    """Signed 64-bit pHash."""
    return to_signed(_bits(imagehash.phash(image)))


def dhash(image: PILImage.Image) -> int:
    """Signed 64-bit dHash."""
    return to_signed(_bits(imagehash.dhash(image)))


def hamming(a: int, b: int) -> int:
    return (to_unsigned(a) ^ to_unsigned(b)).bit_count()


def bands(phash_signed: int) -> list[int]:
    """Bucket keys of a pHash: band index in the high bits, band bits in the low byte."""
    value = to_unsigned(phash_signed)
    keys: list[int] = []
    shift = 0
    for index, width in enumerate(BAND_WIDTHS):
        keys.append((index << 8) | ((value >> shift) & ((1 << width) - 1)))
        shift += width
    return keys


def thumbnail_jpeg(image: PILImage.Image) -> bytes:
    thumb = image.copy()
    thumb.thumbnail((THUMBNAIL_SIDE, THUMBNAIL_SIDE))
    out = io.BytesIO()
    thumb.save(out, format="JPEG", quality=85)
    return out.getvalue()
