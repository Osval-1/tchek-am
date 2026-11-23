from django.db import models


class AICallLog(models.Model):
    """One row per LLM call, for cost and quality tracking.

    Never holds prompt or response content: only metadata about the call.
    """

    purpose = models.CharField(max_length=50, db_index=True)
    # The model that served the call, which may be a server-side fallback.
    model = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=20, blank=True)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    success = models.BooleanField()
    # Exception class name, "invalid_output", "refusal:<category>" or "max_tokens".
    error = models.CharField(max_length=100, blank=True)
    request_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "AI call log"

    def __str__(self):
        status = "ok" if self.success else self.error
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.purpose} {status}"
