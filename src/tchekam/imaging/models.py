from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone
from pgvector.django import HnswIndex, VectorField

EMBEDDING_DIM = 512


class Image(models.Model):
    """A distinct picture, keyed by the sha256 of its bytes, with the hashes used to find copies.

    Only the 256 px thumbnail is kept in the ObjectStore; the original bytes are not stored here.
    Rows created before Issue 17 (report stubs) have no hashes, hence the nullable fields.
    """

    class Source(models.TextChoices):
        SUBMISSION = "submission"
        GROUP = "group"
        CATALOGUE = "catalogue"

    sha256 = models.CharField(max_length=64, unique=True)
    # 64-bit hashes stored as *signed* bigint (Postgres has no unsigned): see hashing.to_signed.
    phash = models.BigIntegerField(null=True, blank=True)
    dhash = models.BigIntegerField(null=True, blank=True)
    # Pigeonhole bucket keys of phash, GIN-indexed, so near-duplicate search never scans the table.
    phash_bands = ArrayField(models.SmallIntegerField(), default=list, blank=True)
    embedding = VectorField(dimensions=EMBEDDING_DIM, null=True, blank=True)
    thumbnail_key = models.CharField(max_length=200, blank=True, default="")
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    first_seen = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.SUBMISSION)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            GinIndex(fields=["phash_bands"], name="imaging_image_phash_bands_gin"),
            HnswIndex(
                name="imaging_image_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"Image#{self.pk}"


class ImageSighting(models.Model):
    """One occasion on which an image was seen. Sightings are what link an image to numbers."""

    class Context(models.TextChoices):
        SUBMISSION = "submission"
        GROUP = "group"
        REPORT = "report"

    image = models.ForeignKey(Image, on_delete=models.CASCADE, related_name="sightings")
    phone_number = models.ForeignKey(
        "identifiers.PhoneNumber", null=True, blank=True, on_delete=models.SET_NULL
    )
    # SET_NULL so erasing a user keeps the sighting but drops the link to them.
    bot_user = models.ForeignKey(
        "conversations.BotUser", null=True, blank=True, on_delete=models.SET_NULL
    )
    # Placeholder for the PartnerGroup FK: that model arrives in Issue 20, which will turn this
    # into `group = ForeignKey(...)` on the same `group_id` column. Never exposed in search results.
    group_id = models.PositiveBigIntegerField(null=True, blank=True)
    seen_at = models.DateTimeField(default=timezone.now)
    context = models.CharField(max_length=12, choices=Context.choices)

    def __str__(self) -> str:
        return f"Sighting of Image#{self.image_id} ({self.context})"


class WebSearchResult(models.Model):
    """Web matches for one image, keyed by sha256, reused for 30 days (see webcheck.CACHE_DAYS).

    Doubles as what moderators see for report images: unlike Evidence.ai_extraction (rewritten
    on every extraction) or Evidence.tamper_flags (a list that lowers the evidence score), it
    is neither overwritten by re-extraction nor counted as tampering. Rows are kept past
    expiry so the review page can still show the last result.
    """

    sha256 = models.CharField(max_length=64, unique=True)
    matches = models.JSONField(default=list)  # WebMatch.to_json() dicts
    checked_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"WebSearchResult {self.sha256[:8]}"


class WebSearchUsage(models.Model):
    """One billable provider call. Counted for the per-user daily cap and the monthly budget."""

    class Purpose(models.TextChoices):
        SUBMISSION = "submission"
        REPORT = "report"

    # SET_NULL so erasing a user keeps the spend record without the link to them.
    user = models.ForeignKey(
        "conversations.BotUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    purpose = models.CharField(max_length=12, choices=Purpose.choices)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["created_at"]), models.Index(fields=["user", "created_at"])]

    def __str__(self) -> str:
        return f"WebSearchUsage#{self.pk} ({self.purpose})"
