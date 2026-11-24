from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.core.audit import audit
from tchekam.identifiers.models import AccountName, PhoneNumber
from tchekam.imaging.models import Image

from .keys import reporter_key_for
from .signals import report_status_changed
from .transitions import InvalidTransition, check_transition

# Only live reports can absorb duplicates; merging into draft/rejected/withdrawn/merged is nonsense.
MERGE_TARGET_STATUSES = frozenset({"pending", "needs_info", "approved"})


class Report(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        PENDING = "pending"
        NEEDS_INFO = "needs_info"
        APPROVED = "approved"
        REJECTED = "rejected"
        MERGED = "merged"
        WITHDRAWN = "withdrawn"  # consent declined or cancelled; terminal, purged by retention

    class ScamType(models.TextChoices):
        MOMO_FRAUD = "momo_fraud"
        FAKE_PRODUCT = "fake_product"
        ADVANCE_FEE = "advance_fee"
        OTHER = "other"

    reference = models.CharField(max_length=12, unique=True, null=True, blank=True)  # noqa: DJ001  # NULL until submission (Issue 12)
    # SET_NULL: erasing a user anonymises their reports instead of deleting them (Issue 24).
    reporter = models.ForeignKey(
        BotUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="reports"
    )
    # Survives erasure, so an erased reporter's reports still count as one person (ADR-005).
    reporter_key = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_reports"
    )
    # Personal data (the reporter's own words): covered by retention (Issue 24), never logged.
    story_text = models.TextField(blank=True)
    # Full AI Extraction dump plus "inputs_key", the fingerprint of the evidence it was run on.
    ai_extraction = models.JSONField(default=dict, blank=True)
    summary_ai = models.TextField(blank=True)
    summary_final = models.TextField(blank=True)
    amount_xaf = models.PositiveIntegerField(null=True, blank=True)
    incident_date = models.DateField(null=True, blank=True)
    scam_type = models.CharField(max_length=20, choices=ScamType.choices, blank=True)
    evidence_score = models.FloatField(default=0.0)  # 0-1
    has_payment_proof = models.BooleanField(default=False)  # moderator-confirmed
    consent_at = models.DateTimeField(null=True, blank=True)
    false_report_warning_ack = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    legal_hold = models.BooleanField(default=False)
    # Set by retention (Issue 24, ADR-022) when evidence and personal fields were deleted:
    # rejected reports after 90 days, approved reports after 36 months. Never reopened then.
    minimised_at = models.DateTimeField(null=True, blank=True)
    # What a minimised rejected report keeps of its subjects: reporter_key_for() of each
    # phone subject (HMAC, not reversible without REPORTER_KEY_SECRET).
    subject_phone_keys = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            # A live reporter always has a key, so independence never has to guess identity.
            models.CheckConstraint(
                name="report_reporter_has_key",
                condition=Q(reporter__isnull=True) | ~Q(reporter_key=""),
            )
        ]

    def __str__(self) -> str:
        return f"Report {self.reference or self.pk} ({self.status})"

    def save(self, *args, **kwargs) -> None:
        # Runs before every save, so the constraint above always holds for saved reports.
        # Set once and never rewritten: rotating the secret must not split a reporter in two.
        if self.reporter_id and not self.reporter_key:
            self.reporter_key = reporter_key_for(self.reporter.wa_phone)
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "reporter_key"}
        super().save(*args, **kwargs)

    _TRANSITION_FIELDS = ("status", "submitted_at", "decided_at", "last_activity_at", "merged_into")

    def transition(self, to: str, actor=None, reason: str = "") -> None:
        """Move along the status graph, stamping dates and auditing. actor=None for system/bot."""
        self._transition(to, actor, reason)

    def _transition(self, to, actor, reason, merged_into=None) -> None:
        with transaction.atomic():
            # Lock and re-read: a stale in-memory copy must not bypass the graph.
            # Both rows are locked in pk order so concurrent merges cannot deadlock.
            pks = sorted({self.pk, merged_into.pk} if merged_into is not None else {self.pk})
            locked = {
                r.pk: r
                for r in type(self).objects.select_for_update().filter(pk__in=pks).order_by("pk")
            }
            row = locked[self.pk]
            old = row.status
            if merged_into is not None:
                target = locked.get(merged_into.pk)
                if target is None or target.status not in MERGE_TARGET_STATUSES:
                    raise InvalidTransition("merge target must be pending, needs_info or approved")
            check_transition(old, to)
            if row.minimised_at is not None and to == self.Status.PENDING:
                raise InvalidTransition("evidence was deleted by retention; cannot reopen")
            now = timezone.now()
            row.status = to
            if to == self.Status.PENDING and row.submitted_at is None:
                row.submitted_at = now
            if to in (self.Status.APPROVED, self.Status.REJECTED, self.Status.MERGED):
                row.decided_at = now
            row.last_activity_at = now
            if merged_into is not None:
                row.merged_into = merged_into
            row.save(update_fields=list(self._TRANSITION_FIELDS))
            audit(actor, "report.transition", row, from_=old, to=to, reason=reason)
            transaction.on_commit(
                lambda: report_status_changed.send(
                    sender=type(self), report=row, from_status=old, to_status=to
                )
            )
        for name in self._TRANSITION_FIELDS:
            attr = self._meta.get_field(name).attname
            setattr(self, attr, getattr(row, attr))
        self._state.fields_cache.pop("merged_into", None)

    def merge_into(self, target: "Report", actor=None) -> None:
        if target.pk == self.pk:
            raise InvalidTransition("cannot merge a report into itself")
        self._transition(self.Status.MERGED, actor, f"merged into {target.pk}", merged_into=target)


class Evidence(models.Model):
    class Kind(models.TextChoices):
        CHAT = "chat"
        MOMO_SMS = "momo_sms"
        POST = "post"
        VOICE = "voice"
        OTHER = "other"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="evidence")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OTHER)
    object_key = models.CharField(max_length=255, unique=True)
    mimetype = models.CharField(max_length=100)
    # Not unique: duplicate detection (Issue 16) needs to see repeats.
    sha256 = models.CharField(max_length=64, db_index=True)
    size_bytes = models.PositiveIntegerField()
    transcript = models.TextField(blank=True)
    transcript_confidence = models.FloatField(null=True, blank=True)
    ai_extraction = models.JSONField(default=dict, blank=True)
    tamper_flags = models.JSONField(default=list, blank=True)
    training_opt_in = models.BooleanField(default=False)
    legal_hold = models.BooleanField(default=False)
    # The WhatsApp message the file came from; makes media ingestion idempotent.
    source_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["report", "source_message_id"],
                condition=~Q(source_message_id=""),
                name="unique_evidence_per_source_message",
            )
        ]

    def __str__(self) -> str:
        return f"Evidence#{self.pk} ({self.kind})"


class ReportSubject(models.Model):
    class Role(models.TextChoices):
        SELLER = "seller"
        PAYEE = "payee"
        PRODUCT = "product"

    class Source(models.TextChoices):
        AI = "ai"
        USER = "user"
        MODERATOR = "moderator"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="subjects")
    # PROTECT: identifiers carry reputation history and must not vanish under a report.
    phone_number = models.ForeignKey(PhoneNumber, null=True, blank=True, on_delete=models.PROTECT)
    account_name = models.ForeignKey(AccountName, null=True, blank=True, on_delete=models.PROTECT)
    image = models.ForeignKey(Image, null=True, blank=True, on_delete=models.PROTECT)
    role = models.CharField(max_length=10, choices=Role.choices)
    source = models.CharField(max_length=10, choices=Source.choices)
    confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["phone_number", "report"])]
        constraints = [
            models.CheckConstraint(
                name="reportsubject_exactly_one_target",
                condition=(
                    Q(phone_number__isnull=False, account_name__isnull=True, image__isnull=True)
                    | Q(phone_number__isnull=True, account_name__isnull=False, image__isnull=True)
                    | Q(phone_number__isnull=True, account_name__isnull=True, image__isnull=False)
                ),
            )
        ]

    def __str__(self) -> str:
        return f"ReportSubject#{self.pk} ({self.role})"


class ReportLink(models.Model):
    """Report pair; unique per (a, b, reason), so one pair can be linked for several reasons."""

    class Reason(models.TextChoices):
        SAME_NUMBER = "same_number"
        SAME_NAME = "same_name"
        SAME_IMAGE = "same_image"
        SIMILAR_TEXT = "similar_text"

    report_a = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="+")
    report_b = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=15, choices=Reason.choices)
    score = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["report_a", "report_b", "reason"], name="unique_reportlink_pair_reason"
            ),
            # Pairs are stored ordered so (a, b) and (b, a) cannot both exist.
            models.CheckConstraint(
                name="reportlink_ordered_pair", condition=Q(report_a_id__lt=F("report_b_id"))
            ),
        ]

    def __str__(self) -> str:
        return f"ReportLink#{self.pk} ({self.reason})"

    @classmethod
    def link(cls, a: Report, b: Report, reason: str, score: float) -> "ReportLink":
        if a.pk == b.pk:
            raise ValueError("cannot link a report to itself")
        lo, hi = (a, b) if a.pk < b.pk else (b, a)
        obj, _ = cls.objects.get_or_create(
            report_a=lo, report_b=hi, reason=reason, defaults={"score": score}
        )
        return obj


class ModerationDecision(models.Model):
    class Action(models.TextChoices):
        APPROVE = "approve"
        REJECT = "reject"
        NEED_INFO = "need_info"
        MERGE = "merge"
        REOPEN = "reopen"

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="decisions")
    moderator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=10, choices=Action.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Claimed (set atomically) by whoever sends or queues the reporter's notification; makes
    # the notify task idempotent.
    notified_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"ModerationDecision#{self.pk} ({self.action})"


class PendingNotification(models.Model):
    """A decision message held back because the reporter's 24 h reply window had closed.

    Delivered, once, on the reporter's next inbound message (ADR-011: no unsolicited messages).
    """

    user = models.ForeignKey(BotUser, on_delete=models.CASCADE, related_name="+")
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="+")
    decision = models.OneToOneField(
        ModerationDecision, on_delete=models.CASCADE, related_name="pending_notification"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "delivered_at"])]

    def __str__(self) -> str:
        return f"PendingNotification#{self.pk}"
