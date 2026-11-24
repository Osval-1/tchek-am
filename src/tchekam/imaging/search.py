"""Find images that are copies of, or near-duplicates of, a given image."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.db.models import IntegerField
from django.db.models.expressions import RawSQL
from pgvector.django import CosineDistance

from . import hashing
from .models import Image, ImageSighting

MIN_COSINE = 0.92
MAX_MATCHES = 20
# Bands reputation treats as "reviewed reports exist"; imported lazily to keep imaging standalone.
_FLAGGED_BANDS = frozenset({"orange", "red"})

BandLookup = Callable[[str], str]


@dataclass(frozen=True)
class Match:
    """A matched image and what we know about where it was seen.

    Deliberately carries no group or reporter identity (PRD: results never include the source
    group). `phone_numbers` is raw data; callers decide what a user may see.
    """

    image_id: int
    kind: str  # "exact" | "phash" | "embedding": the strongest signal that matched
    phash_distance: int | None
    similarity: float | None  # cosine similarity, when an embedding comparison was possible
    first_seen: datetime
    phone_numbers: tuple[str, ...]
    sighting_count: int
    has_flagged_number: bool  # any linked number is in the orange or red band


def find_similar(image: Image, band_lookup: BandLookup | None = None) -> list[Match]:
    """Matches for `image`, strongest first. Includes `image` itself (the exact sha256 match).

    `band_lookup` maps an E.164 number to its band name; it defaults to the reputation service.
    """
    found: dict[int, tuple[str, int | None, float | None]] = {image.pk: ("exact", None, None)}
    for pk, distance in _phash_candidates(image):
        found.setdefault(pk, ("phash", distance, None))
    for pk, similarity in _embedding_candidates(image):
        kind, distance, _ = found.get(pk, ("embedding", None, None))
        found[pk] = (kind, distance, similarity)
    return _summaries(found, band_lookup)[:MAX_MATCHES]


def _phash_candidates(image: Image) -> list[tuple[int, int]]:
    if image.phash is None:
        return []
    # Pigeonhole prefilter via the GIN-indexed bands, then the exact Hamming distance in SQL.
    # bit_count() takes bit strings, hence the cast.
    distance = RawSQL(
        'bit_count(("imaging_image"."phash" # %s::bigint)::bit(64))',
        [image.phash],
        output_field=IntegerField(),
    )
    rows = (
        Image.objects.filter(phash_bands__overlap=hashing.bands(image.phash))
        .exclude(pk=image.pk)
        .annotate(distance=distance)
        .values_list("pk", "distance")
    )
    return [(pk, d) for pk, d in rows if d is not None and d <= hashing.MAX_PHASH_DISTANCE]


def _embedding_candidates(image: Image) -> list[tuple[int, float]]:
    if image.embedding is None:
        return []
    rows = (
        Image.objects.exclude(pk=image.pk)
        .exclude(embedding=None)
        .annotate(distance=CosineDistance("embedding", image.embedding))
        .filter(distance__lte=1 - MIN_COSINE)
        .order_by("distance")
        .values_list("pk", "distance")[:MAX_MATCHES]
    )
    return [(pk, 1 - d) for pk, d in rows]


def _summaries(
    found: dict[int, tuple[str, int | None, float | None]], band_lookup: BandLookup | None
) -> list[Match]:
    numbers: dict[int, set[str]] = defaultdict(set)
    counts: dict[int, int] = defaultdict(int)
    sightings = ImageSighting.objects.filter(image_id__in=found).values_list(
        "image_id", "phone_number__e164"
    )
    for image_id, e164 in sightings:
        counts[image_id] += 1
        if e164:
            numbers[image_id].add(e164)
    flagged = _flagged(set().union(*numbers.values()), band_lookup)
    order = {"exact": 0, "phash": 1, "embedding": 2}
    matches = [
        Match(
            image_id=image.pk,
            kind=found[image.pk][0],
            phash_distance=found[image.pk][1],
            similarity=found[image.pk][2],
            first_seen=image.first_seen,
            phone_numbers=tuple(sorted(numbers[image.pk])),
            sighting_count=counts[image.pk],
            has_flagged_number=any(n in flagged for n in numbers[image.pk]),
        )
        for image in Image.objects.filter(pk__in=found).only("first_seen")
    ]
    matches.sort(key=lambda m: (order[m.kind], m.phash_distance or 0, -(m.similarity or 0)))
    return matches


def _flagged(e164s: set[str], band_lookup: BandLookup | None) -> set[str]:
    if not e164s:
        return set()
    if band_lookup is None:
        from tchekam.reputation.service import band_for_phone

        def band_lookup(e164: str) -> str:
            return band_for_phone(e164).band

    return {e164 for e164 in e164s if str(band_lookup(e164)) in _FLAGGED_BANDS}
