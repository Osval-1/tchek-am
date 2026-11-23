"""DB -> facts -> rules, with a 1 h cache per number. The only module here that touches Django.

Expiry is what makes decay happen without new events: a cached band is at most an hour stale.
"""

from datetime import datetime

from django.core.cache import cache
from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

from tchekam.reports.keys import reporter_key_for
from tchekam.reports.models import Evidence, Report, ReportSubject

from . import appeals_hook
from .facts import BandResult, ReportFacts
from .rules import compute_band

CACHE_TIMEOUT = 3600  # seconds


def cache_key(e164: str) -> str:
    return f"reputation:phone:{e164}"


def band_for_phone(e164: str, now: datetime | None = None) -> BandResult:
    """The public band for a number. Passing `now` (tests, backfills) bypasses the cache."""
    if now is not None:
        return _compute(e164, now)
    key = cache_key(e164)
    result = cache.get(key)
    if result is None:
        result = _compute(e164, timezone.now())
        cache.set(key, result, CACHE_TIMEOUT)
    return result


def invalidate_phone(e164: str) -> None:
    cache.delete(cache_key(e164))


def invalidate_report(report: Report) -> None:
    """Drop the cached band of every number the report names."""
    numbers = ReportSubject.objects.filter(report=report, phone_number__isnull=False).values_list(
        "phone_number__e164", flat=True
    )
    cache.delete_many([cache_key(e164) for e164 in set(numbers)])


def _compute(e164: str, now: datetime) -> BandResult:
    facts = [_facts(r) for r in _reports_naming(e164)]
    # Local time so ages are counted in Cameroonian calendar days.
    return compute_band(facts, timezone.localtime(now), appeals_hook.get_appeal_state(e164))


def _reports_naming(e164: str) -> QuerySet[Report]:
    # One filter() call, so both conditions apply to the same subject row: an approved report
    # counts only once a moderator has confirmed that this number is its subject.
    names_it = Q(subjects__phone_number__e164=e164)
    counted = Q(status=Report.Status.APPROVED, subjects__confirmed=True) | Q(
        status__in=[Report.Status.PENDING, Report.Status.NEEDS_INFO]
    )
    phone_subjects = ReportSubject.objects.filter(phone_number__isnull=False).select_related(
        "phone_number"
    )
    return (
        Report.objects.filter(names_it & counted)
        .distinct()
        .select_related("reporter")
        .prefetch_related(
            Prefetch("subjects", queryset=phone_subjects),
            Prefetch("evidence", queryset=Evidence.objects.only("id", "report_id", "sha256")),
        )
    )


# An erased reporter's real trust is gone (Issue 24 will keep it). Treat them as below the
# floor: losing information about a reporter must never make a band worse.
ERASED_REPORTER_TRUST = 0.0


def _facts(r: Report) -> ReportFacts:
    reporter = r.reporter
    # Every phone subject, confirmed or not: for independence, an unconfirmed mention of
    # another reporter's number is still a reason to doubt that they are independent. (The
    # confirmed filter only decides whether the report counts against the checked number.)
    phones = frozenset(s.phone_number.e164 for s in r.subjects.all())
    return ReportFacts(
        report_id=r.pk,
        status=r.status,
        reporter_key=r.reporter_key,
        reporter_phone=reporter.wa_phone if reporter else None,
        reporter_trust=reporter.trust_weight if reporter else ERASED_REPORTER_TRUST,
        submitted_at=r.submitted_at,
        decided_at=r.decided_at,
        incident_date=r.incident_date,
        has_payment_proof=r.has_payment_proof,
        subject_phones=phones,
        subject_keys=frozenset(reporter_key_for(p) for p in phones),
        evidence_sha256s=frozenset(e.sha256 for e in r.evidence.all()),
        summary=r.summary_final or "",
    )
