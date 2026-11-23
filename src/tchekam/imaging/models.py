from django.db import models


class Image(models.Model):
    """Stub so ReportSubject can reference an image; Issue 17 adds hashes and embeddings."""

    sha256 = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Image#{self.pk}"
