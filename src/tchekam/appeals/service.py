"""Appeal rules: eligibility, submission and the moderator's decision.

Decisions lock the Appeal row, change everything in one transaction and schedule cache
invalidation and the appellant's notification for after commit. Statements, reasons and
numbers are never logged or audited (ids and field names only).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.core.audit import audit
from tchekam.core.tasks import enqueue
from tchekam.reports.models import ModerationDecision, Report
from tchekam.reports.transitions import InvalidTransition
from tchekam.reports.weighting import recompute as recompute_trust
from tchekam.reputation.service import invalidate_phone

from .models import Appeal

MAX_STATEMENT = 1000
APPROVE, REJECT = "approve", "reject"


class AppealError(Exception):
    """A problem the moderator can fix; carries a message safe to show."""


class Refusal(StrEnum):
    ALREADY_OPEN = "already_open"  # this user already has an open appeal
    NUMBER_BUSY = "number_busy"  # someone has an open appeal on this number
    LIMIT = "limit"  # too many appeals today


def _day_start():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def refusal_for(user: BotUser, phone_id: int | None) -> Refusal | None:
    """Why this user cannot open another appeal now, if anything stops them."""
    if Appeal.objects.filter(appellant=user, status=Appeal.Status.OPEN).exists():
        return Refusal.ALREADY_OPEN
    if phone_id and Appeal.objects.filter(phone_number_id=phone_id, status="open").exists():
        # Someone else's open appeal on this number is not duplicated: one review decides.
        return Refusal.NUMBER_BUSY
    submitted = Appeal.objects.filter(appellant=user, submitted_at__gte=_day_start()).count()
    if submitted >= settings.APPEALS_PER_DAY:
        return Refusal.LIMIT
    return None


def submit(appeal: Appeal) -> Refusal | None:
    """Make a draft visible to moderators and to the band. None on success."""
    with transaction.atomic():
        locked = Appeal.objects.select_for_update().select_related("phone_number").get(pk=appeal.pk)
        if locked.status != Appeal.Status.DRAFT:
            return Refusal.ALREADY_OPEN
        if locked.appellant and (refusal := refusal_for(locked.appellant, locked.phone_number_id)):
            return refusal
        locked.status = Appeal.Status.OPEN
        locked.submitted_at = timezone.now()
        try:
            with transaction.atomic():
                locked.save(update_fields=["status", "submitted_at"])
        except IntegrityError:  # a concurrent submit won the unique constraints
            return Refusal.NUMBER_BUSY
        audit(None, "appeal.submit", locked, kind=locked.kind)
        e164 = locked.phone_number.e164
        transaction.on_commit(lambda: invalidate_phone(e164))
    return None


@dataclass(frozen=True)
class Decision:
    appeal: Appeal
    rejected_reports: list[int]


def appealable_reports(appeal: Appeal):
    """Reports that count against the appealed number: approved ones with a confirmed subject,
    and pending / needs-info ones (the band counts those whether or not the subject is confirmed,
    so a yellow number can be cleared too)."""
    counted = Q(status=Report.Status.APPROVED, subjects__confirmed=True) | Q(
        status__in=[Report.Status.PENDING, Report.Status.NEEDS_INFO]
    )
    return Report.objects.filter(counted, subjects__phone_number=appeal.phone_number_id).distinct()


def decide(
    appeal_id: int,
    actor: AbstractBaseUser,
    action: str,
    reason: str = "",
    report_ids: Iterable[int] = (),
    ip: str | None = None,
) -> Decision:
    """Approve or reject an open appeal, atomically."""
    reason = reason.strip()
    if action not in (APPROVE, REJECT):
        raise AppealError("Choose approve or reject.")
    if action == REJECT and not reason:
        raise AppealError("A reason is required to reject an appeal.")
    ids = sorted({int(i) for i in report_ids})
    with transaction.atomic():
        appeal = Appeal.objects.select_for_update().select_related("phone_number").get(pk=appeal_id)
        # Re-checked under the lock: a double submit finds it decided and changes nothing.
        if appeal.status != Appeal.Status.OPEN:
            raise AppealError("This appeal has already been decided.")
        rejected: list[int] = []
        if action == APPROVE and appeal.kind == Appeal.Kind.WRONG:
            # An approval that changes nothing would be a silent rejection: require reports.
            if not ids:
                raise AppealError("Select at least one report to reject, or reject the appeal.")
            rejected = _reject_reports(appeal, ids, actor)
        appeal.status = Appeal.Status.APPROVED if action == APPROVE else Appeal.Status.REJECTED
        appeal.decided_by = actor
        appeal.decided_at = timezone.now()
        appeal.reason = reason
        appeal.save(update_fields=["status", "decided_by", "decided_at", "reason"])
        audit(actor, f"appeal.{action}", appeal, ip=ip, kind=appeal.kind, reports=rejected)
        e164 = appeal.phone_number.e164
        transaction.on_commit(lambda: invalidate_phone(e164))
        transaction.on_commit(lambda: enqueue("appeals.notify_decided", appeal_id=appeal_id))
    return Decision(appeal, rejected)


def _reject_reports(appeal: Appeal, ids: list[int], actor: AbstractBaseUser) -> list[int]:
    valid = set(appealable_reports(appeal).filter(pk__in=ids).values_list("pk", flat=True))
    if valid != set(ids):
        raise AppealError("A selected report is not a live report of this number.")
    phones: set[str] = set()
    for report in Report.objects.filter(pk__in=ids).select_related("reporter").order_by("pk"):
        decision = ModerationDecision.objects.create(
            report=report, moderator=actor, action="reject", reason="appeal"
        )
        # Through the status graph, so audit and the band's cache signal fire as usual.
        try:
            report.transition(Report.Status.REJECTED, actor=actor, reason="appeal")
        except InvalidTransition as exc:  # decided by someone else since the page was loaded
            raise AppealError(
                "A selected report changed in the meantime. Reload the page."
            ) from exc
        if report.reporter_id:
            phones |= recompute_trust(report.reporter)
        transaction.on_commit(
            lambda r=report.pk, d=decision.pk: enqueue(
                "notify.report_decided", report_id=r, decision_id=d
            )
        )
    for e164 in phones:  # a changed reporter weight feeds other numbers' bands
        transaction.on_commit(lambda e=e164: invalidate_phone(e))
    return ids
