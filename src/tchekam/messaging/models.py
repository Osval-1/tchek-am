from typing import Any

from django.db import models

from .channel import InboundMessage
from .parser import scrubbed_group_payload


class InboundEvent(models.Model):
    """One webhook delivery, keyed by provider message id so redeliveries are no-ops."""

    class Status(models.TextChoices):
        RECEIVED = "received"
        PROCESSING = "processing"
        PROCESSED = "processed"
        FAILED = "failed"
        IGNORED = "ignored"

    message_id = models.CharField(max_length=255, unique=True)
    event = models.CharField(max_length=100)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    # Set when a worker claims the event; the recovery job resets stale claims.
    claimed_at = models.DateTimeField(null=True, blank=True)
    # Claims so far (rate-limit requeues excluded): caps crash loops and error retries.
    attempts = models.PositiveSmallIntegerField(default=0)
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

    def scrub_group_payload(self) -> bool:
        """Drop the poster and media pointers of a group event that will not be ingested."""
        scrubbed = scrubbed_group_payload(self.payload)
        if scrubbed is None:
            return False
        self.payload = scrubbed
        self.save(update_fields=["payload"])
        return True

    @classmethod
    def scrub_group(cls, message_id: str) -> None:
        event = cls.objects.filter(message_id=message_id).first()
        if event is not None:
            event.scrub_group_payload()


class ChannelState(models.Model):
    """Which WaSender session is live. One row (pk=1), written by `switch_channel`."""

    class Session(models.TextChoices):
        PRIMARY = "primary"
        BACKUP = "backup"

    active_session = models.CharField(
        max_length=10, choices=Session.choices, default=Session.PRIMARY
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"active session: {self.active_session}"

    @classmethod
    def current(cls) -> str:
        """The switched value if an operator ever switched, else the setting."""
        from django.conf import settings

        row = cls.objects.filter(pk=1).first()
        return row.active_session if row else settings.WASENDER_ACTIVE_SESSION

    @classmethod
    def switch(cls, session: str) -> None:
        cls.objects.update_or_create(pk=1, defaults={"active_session": session})


class SendBucket(models.Model):
    """The global token bucket (one row, pk=1). Only touched under the limiter's advisory lock."""

    tokens = models.FloatField()
    updated_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.tokens:.1f} tokens"


class RecipientSend(models.Model):
    """Sliding log of recent sends per recipient; the recipient is stored as a keyed hash."""

    recipient_hash = models.CharField(max_length=64)
    sent_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["recipient_hash", "sent_at"])]

    def __str__(self) -> str:
        return f"{self.recipient_hash[:8]} at {self.sent_at}"
