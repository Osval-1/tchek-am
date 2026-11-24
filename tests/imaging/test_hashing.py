import io

import pytest
from PIL import Image

from tchekam.imaging import hashing

from .helpers import VARIANTS, encode, structured_image


def test_signed_conversion_round_trips_full_64_bit_range():
    for unsigned in (0, 1, (1 << 63) - 1, 1 << 63, (1 << 64) - 1, 0xDEADBEEFCAFEF00D):
        signed = hashing.to_signed(unsigned)
        assert -(1 << 63) <= signed < (1 << 63)
        assert hashing.to_unsigned(signed) == unsigned


def test_phash_fits_postgres_bigint_and_is_deterministic():
    img = structured_image(3)
    assert hashing.phash(img) == hashing.phash(img)
    assert -(1 << 63) <= hashing.phash(img) < (1 << 63)


@pytest.mark.parametrize("name", VARIANTS)
def test_variants_are_within_phash_threshold(name):
    original = structured_image(4)
    distance = hashing.hamming(hashing.phash(original), hashing.phash(VARIANTS[name](original)))
    assert distance <= hashing.MAX_PHASH_DISTANCE


def test_unrelated_image_is_far():
    a, b = structured_image(4), structured_image(2)
    assert hashing.hamming(hashing.phash(a), hashing.phash(b)) > hashing.MAX_PHASH_DISTANCE


def test_bands_pigeonhole_never_misses_distance_8():
    import random

    rng = random.Random(7)
    for _ in range(2000):
        a = rng.getrandbits(64)
        flips = rng.sample(range(64), rng.randint(0, 8))
        b = a
        for bit in flips:
            b ^= 1 << bit
        shared = set(hashing.bands(hashing.to_signed(a))) & set(hashing.bands(hashing.to_signed(b)))
        assert shared, (a, b)


def test_band_keys_fit_smallint():
    assert all(0 <= k < 32768 for k in hashing.bands(-1))
    assert len(hashing.bands(0)) == 9


def test_decode_rejects_garbage_empty_and_oversize(monkeypatch):
    for bad in (b"", b"not an image", b"\x89PNG\r\n\x1a\n" + b"x" * 20):
        with pytest.raises(hashing.ImageRejected):
            hashing.decode(bad)
    monkeypatch.setattr(hashing, "MAX_IMAGE_BYTES", 100)
    with pytest.raises(hashing.ImageRejected):
        hashing.decode(encode(structured_image(4)))


def test_decode_rejects_pixel_bombs_and_unsupported_formats(monkeypatch):
    monkeypatch.setattr(hashing, "MAX_PIXELS", 100)
    with pytest.raises(hashing.ImageRejected):
        hashing.decode(encode(Image.new("RGB", (50, 50))))
    monkeypatch.setattr(hashing, "MAX_PIXELS", 40_000_000)
    with pytest.raises(hashing.ImageRejected):
        hashing.decode(encode(Image.new("RGB", (8, 8)), "BMP"))


def test_thumbnail_is_256px_jpeg():
    thumb = Image.open(io.BytesIO(hashing.thumbnail_jpeg(structured_image(4, size=800))))
    assert thumb.format == "JPEG"
    assert max(thumb.size) == 256
