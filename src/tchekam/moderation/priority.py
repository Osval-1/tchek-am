"""Review queue ordering (ADR-004): demand x evidence quality x scam severity."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.db.models import Count, Prefetch
from django.utils import timezone

from tchekam.checks.models import CheckLog
from tchekam.reports.models import Report, ReportSubject

SCAM_WEIGHTS = {"momo_fraud": 3.0, "advance_fee": 2.5, "fake_product": 2.0}
DEFAULT_WEIGHT = 1.0  # other, or not yet classified
CHECK_WINDOW = timedelta(days=7)
QUEUE_STATUSES = [Report.Status.PENDING, Report.Status.NEEDS_INFO]


def priority_score(checks: int, evidence_score: float, scam_type: str) -> float:
    return (checks + 1) * (evidence_score + 0.1) * SCAM_WEIGHTS.get(scam_type, DEFAULT_WEIGHT)


@dataclass(frozen=True)
class QueueRow:
    report: Report
    files: int
    subjects: int
    checks: int
    priority: float


def queue_rows(now: datetime | None = None) -> list[QueueRow]:
    now = now or timezone.now()
    sellers = ReportSubject.objects.filter(
        role=ReportSubject.Role.SELLER, phone_number__isnull=False
    ).select_related("phone_number")
    reports = list(
        Report.objects.filter(status__in=QUEUE_STATUSES)
        .annotate(
            files=Count("evidence", distinct=True), subject_total=Count("subjects", distinct=True)
        )
        .prefetch_related(Prefetch("subjects", queryset=sellers, to_attr="seller_subjects"))
    )
    phones_of = {r.pk: {s.phone_number.e164 for s in r.seller_subjects} for r in reports}
    refs = set().union(*phones_of.values()) if phones_of else set()
    seen = dict(
        CheckLog.objects.filter(subject_ref__in=refs, created_at__gte=now - CHECK_WINDOW)
        .values_list("subject_ref")
        .annotate(n=Count("id"))
    )
    rows = []
    for r in reports:
        checks = sum(seen.get(p, 0) for p in phones_of[r.pk])
        rows.append(
            QueueRow(
                r,
                r.files,
                r.subject_total,
                checks,
                priority_score(checks, r.evidence_score, r.scam_type),
            )
        )
    # Equal priority: oldest submission first, so nothing waits forever.
    far_future = datetime.max.replace(tzinfo=UTC)
    rows.sort(key=lambda x: (-x.priority, x.report.submitted_at or far_future, x.report.pk))
    return rows
