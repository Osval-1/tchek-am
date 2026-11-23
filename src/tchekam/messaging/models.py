from typing import Any

from django.db import models

from .channel import InboundMessage


class InboundEvent(models.Model):
    """One webhook delivery, keyed by provider message id so redeliveries are no-ops."""

    class Status(models.TextChoices):
        RECEIVED = "received"
        PROCESSED = "processed"
        FAILED = "failed"
        IGNORED = "ignored"

    message_id = models.CharField(max_length=255, unique=True)
    event = models.CharField(max_length=100)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-received_at", "-id"]

    def __str__(self) -> str:
        return f"{self.event} {self.message_id} ({self.status})"

    @classmethod
    def record(cls, msg: InboundMessage, payload: dict[str, Any]) -> tuple["InboundEvent", bool]:
        """Store the delivery once. Returns (event, created); safe under concurrent duplicates."""
        # get_or_create retries the lookup on IntegrityError, so racing duplicates converge.
        return cls.objects.get_or_create(
            message_id=msg.message_id, defaults={"event": msg.raw_event, "payload": payload}
        )
