"""What retention keeps after it deletes (ADR-013, ADR-022)."""

from django.db import models


class TrainingSample(models.Model):
    """A copy of an opted-in voice note, under the `training/` prefix, for speech models.

    Made when the report is approved or rejected, and kept until the user withdraws consent
    (STOP TRAINING) or their account is erased; independent of the report's own retention.
    """

    # SET_NULL, then deleted by the nightly run: an erased user can no longer consent.
    user = models.ForeignKey(
        "conversations.BotUser",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_samples",
    )
    # The evidence it was copied from; SET_NULL because the copy outlives the evidence.
    evidence = models.OneToOneField(
        "reports.Evidence",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="training_sample",
    )
    audio_key = models.CharField(max_length=255, unique=True)
    mimetype = models.CharField(max_length=100)
    transcript = models.TextField(blank=True)  # what speech-to-text produced
    corrected_transcript = models.TextField(blank=True)  # a human correction, when one exists
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"TrainingSample#{self.pk}"


class CheckLogMonthly(models.Model):
    """Check counts per subject, month (Africa/Douala) and kind, for CheckLog rows older than
    12 months. No user link."""

    subject_ref = models.CharField(max_length=64)  # as CheckLog.subject_ref
    month = models.DateField()  # first day of the month
    kind = models.CharField(max_length=10)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subject_ref", "month", "kind"], name="unique_checklog_monthly"
            )
        ]

    def __str__(self) -> str:
        return f"CheckLogMonthly#{self.pk} ({self.kind}, {self.month:%Y-%m})"


class ReporterTrust(models.Model):
    """A reporter's trust weight that survives losing the account link (ADR-015).

    Written before a BotUser is deleted and before retention drops the reporter from a
    report. Keyed by Report.reporter_key, which is why REPORTER_KEY_SECRET is never rotated.
    """

    reporter_key = models.CharField(max_length=64, unique=True)
    trust_weight = models.FloatField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # The retention app's one custom permission lives here (it needs a concrete model).
        permissions = [("manage_legal_hold", "Can place or release a legal hold")]

    def __str__(self) -> str:
        return f"ReporterTrust#{self.pk}"
