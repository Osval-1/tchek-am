from django.conf import settings
from django.db import models
from django.db.models import Q

from tchekam.conversations.models import BotUser
from tchekam.identifiers.models import PhoneNumber


class Appeal(models.Model):
    """The owner of a reported number contests its reports (F6).

    Only the sender's own number can be appealed (WhatsApp authenticates the sender; there is
    no stronger proof of ownership). `statement` and the evidence rows are personal data:
    covered by retention (Issue 24), never logged.
    """

    class Kind(models.TextChoices):
        WRONG = "wrong"  # "these reports are wrong"
        NEW_TO_ME = "new_to_me"  # recycled number: the reports are about a previous owner

    class Status(models.TextChoices):
        # Being written in the chat flow: invisible to moderators and to the band.
        DRAFT = "draft"
        OPEN = "open"
        APPROVED = "approved"
        REJECTED = "rejected"

    phone_number = models.ForeignKey(PhoneNumber, on_delete=models.PROTECT, related_name="appeals")
    # SET_NULL: erasing a user must not undo an approved "new to me" exclusion on the band.
    appellant = models.ForeignKey(
        BotUser, null=True, on_delete=models.SET_NULL, related_name="appeals"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    statement = models.TextField(blank=True)
    # First day of the month the appellant got the number (month precision). Only an
    # approved appeal makes it count.
    number_acquired_at = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)  # the moderator's own words; never sent to the appellant
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    # Claimed (set atomically) by whoever sends or queues the decision message.
    notified_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # One open appeal per number (nobody else's appeal is duplicated) and per person.
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=Q(status="open"),
                name="appeal_one_open_per_number",
            ),
            models.UniqueConstraint(
                fields=["appellant"],
                condition=Q(status="open"),
                name="appeal_one_open_per_appellant",
            ),
            models.CheckConstraint(
                name="appeal_new_to_me_has_date",
                condition=~Q(kind="new_to_me") | Q(number_acquired_at__isnull=False),
            ),
        ]
        indexes = [models.Index(fields=["appellant", "delivered_at"])]

    def __str__(self) -> str:
        return f"Appeal#{self.pk} ({self.status})"


class AppealEvidence(models.Model):
    """An image or voice note attached to an appeal, stored like report evidence."""

    appeal = models.ForeignKey(Appeal, on_delete=models.CASCADE, related_name="evidence")
    object_key = models.CharField(max_length=255, unique=True)
    mimetype = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64, db_index=True)
    size_bytes = models.PositiveIntegerField()
    # The WhatsApp message the file came from; makes ingestion idempotent.
    source_message_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["appeal", "source_message_id"], name="unique_appeal_evidence_per_message"
            )
        ]

    def __str__(self) -> str:
        return f"AppealEvidence#{self.pk}"
