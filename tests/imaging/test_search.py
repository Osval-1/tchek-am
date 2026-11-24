import random

import pytest
from django.db import connection

from tchekam.identifiers.models import PhoneNumber
from tchekam.imaging import hashing
from tchekam.imaging.ingest import SightingContext, ingest
from tchekam.imaging.models import Image
from tchekam.imaging.search import find_similar

from .helpers import VARIANTS, encode, structured_image

pytestmark = pytest.mark.django_db

SUBMISSION = SightingContext(context="submission")


def ingest_img(img, ctx=SUBMISSION):
    return ingest(encode(img), "submission", ctx)


def hashed_image(sha: str, phash: int, embedding=None, **kw) -> Image:
    return Image.objects.create(
        sha256=sha,
        phash=phash,
        phash_bands=hashing.bands(phash),
        embedding=embedding,
        **kw,
    )


def ids(matches):
    return {m.image_id for m in matches}


@pytest.mark.parametrize("name", VARIANTS)
def test_variants_of_an_image_match_the_original(name):
    original_img = structured_image(4)
    original = ingest_img(original_img)
    variant = ingest_img(VARIANTS[name](original_img))

    matches = {m.image_id: m for m in find_similar(variant)}

    assert original.pk in matches
    assert matches[original.pk].kind in ("phash", "embedding")


def test_unrelated_image_does_not_match():
    original = ingest_img(structured_image(4))
    unrelated = ingest_img(structured_image(2))
    assert ids(find_similar(unrelated)) == {unrelated.pk}
    assert original.pk not in ids(find_similar(unrelated))


def test_exact_match_is_the_image_itself_and_comes_first():
    img = ingest_img(structured_image(4))
    near = ingest_img(VARIANTS["resized"](structured_image(4)))
    matches = find_similar(near)
    assert [m.kind for m in matches][0] == "exact"
    assert matches[0].image_id == near.pk
    assert img.pk in ids(matches)


def test_phash_distance_boundary_is_inclusive_at_8_and_excludes_9():
    base = hashing.to_signed(0x0F0F0F0F0F0F0F0F)
    query = hashed_image("a" * 64, base)
    at_8 = hashed_image("b" * 64, hashing.to_signed(0x0F0F0F0F0F0F0F0F ^ 0xFF))
    at_9 = hashed_image("c" * 64, hashing.to_signed(0x0F0F0F0F0F0F0F0F ^ 0x1FF))

    matches = {m.image_id: m for m in find_similar(query)}

    assert at_8.pk in matches and matches[at_8.pk].phash_distance == 8
    assert at_9.pk not in matches


def test_phash_search_handles_hashes_with_the_sign_bit_set():
    high = hashing.to_signed(0xF000000000000001)
    query = hashed_image("a" * 64, high)
    near = hashed_image("b" * 64, hashing.to_signed(0xF000000000000003))
    assert near.pk in ids(find_similar(query))


def test_bucket_prefilter_misses_nothing_within_distance_8():
    rng = random.Random(11)
    base = rng.getrandbits(64)
    query = hashed_image("q" * 64, hashing.to_signed(base))
    expected = set()
    for i in range(15):  # stay under MAX_MATCHES
        flips = rng.sample(range(64), rng.randint(0, 8))
        value = base
        for bit in flips:
            value ^= 1 << bit
        expected.add(hashed_image(f"n{i:063d}", hashing.to_signed(value)).pk)
    for i in range(40):  # distance almost certainly > 8
        hashed_image(f"f{i:063d}", hashing.to_signed(rng.getrandbits(64)))

    found = ids(find_similar(query)) - {query.pk}
    assert expected <= found


def test_embedding_match_when_phash_differs():
    vec = [1.0] + [0.0] * 511
    close = [0.99, 0.05] + [0.0] * 510
    far = [0.0, 1.0] + [0.0] * 510
    query = hashed_image("a" * 64, 1, embedding=vec)
    near = hashed_image("b" * 64, hashing.to_signed(0xAAAAAAAAAAAAAAAA), embedding=close)
    other = hashed_image("c" * 64, hashing.to_signed(0x5555555555555555), embedding=far)

    matches = {m.image_id: m for m in find_similar(query)}

    assert matches[near.pk].kind == "embedding"
    assert matches[near.pk].similarity >= 0.92
    assert other.pk not in matches


def test_summary_lists_distinct_numbers_first_seen_and_flagged_band():
    img = structured_image(4)
    a = PhoneNumber.objects.create(e164="+237670000001", operator="mtn")
    b = PhoneNumber.objects.create(e164="+237670000002", operator="mtn")
    first = ingest_img(img, SightingContext(context="group", phone_number=a, group_id=9))
    ingest_img(img, SightingContext(context="group", phone_number=a, group_id=9))
    ingest_img(img, SightingContext(context="report", phone_number=b))
    query = ingest_img(VARIANTS["resized"](img))

    match = next(
        m for m in find_similar(query, band_lookup=lambda e164: "green") if m.image_id == first.pk
    )

    assert match.phone_numbers == ("+237670000001", "+237670000002")
    assert match.sighting_count == 3
    assert match.first_seen == first.first_seen
    assert match.has_flagged_number is False

    flagged = find_similar(
        query, band_lookup=lambda e164: "orange" if e164.endswith("2") else "green"
    )
    assert next(m for m in flagged if m.image_id == first.pk).has_flagged_number is True


def test_default_band_lookup_uses_the_reputation_service(monkeypatch):
    from tchekam.reputation import service
    from tchekam.reputation.facts import Band

    phone = PhoneNumber.objects.create(e164="+237670000009", operator="mtn")
    image = ingest_img(structured_image(4), SightingContext(context="report", phone_number=phone))
    monkeypatch.setattr(service, "band_for_phone", lambda e164: type("R", (), {"band": Band.RED})())
    assert find_similar(image)[0].has_flagged_number is True
    monkeypatch.setattr(
        service, "band_for_phone", lambda e164: type("R", (), {"band": Band.GREEN})()
    )
    assert find_similar(image)[0].has_flagged_number is False


def test_match_never_exposes_group_or_reporter_identity():
    from dataclasses import fields

    from tchekam.imaging.search import Match

    names = {f.name for f in fields(Match)}
    assert not {n for n in names if "group" in n or "user" in n or "reporter" in n}


def test_image_without_phash_or_embedding_matches_only_itself():
    bare = Image.objects.create(sha256="z" * 64)
    assert ids(find_similar(bare)) == {bare.pk}


def test_hnsw_and_bands_indexes_exist():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'imaging_image'"
        )
        defs = dict(cursor.fetchall())
    hnsw = defs["imaging_image_embedding_hnsw"]
    assert "USING hnsw" in hnsw and "vector_cosine_ops" in hnsw
    assert "USING gin" in defs["imaging_image_phash_bands_gin"]


@pytest.mark.slow
def test_find_similar_under_200ms_on_10k_rows():
    import time

    import numpy as np

    rng = np.random.default_rng(0)
    py_rng = random.Random(0)
    vectors = rng.normal(size=(10_000, 512))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    rows = []
    for i in range(10_000):
        phash = hashing.to_signed(py_rng.getrandbits(64))
        rows.append(
            Image(
                sha256=f"{i:064d}",
                phash=phash,
                phash_bands=hashing.bands(phash),
                embedding=vectors[i].tolist(),
            )
        )
    Image.objects.bulk_create(rows, batch_size=1000)
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE imaging_image")
    query = Image.objects.get(sha256=f"{5:064d}")
    find_similar(query, band_lookup=lambda e164: "green")  # warm up

    started = time.perf_counter()
    find_similar(query, band_lookup=lambda e164: "green")
    elapsed = time.perf_counter() - started

    assert elapsed < 0.2, f"{elapsed * 1000:.0f} ms"
