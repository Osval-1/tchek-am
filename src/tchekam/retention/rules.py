"""Retention rules (ADR-013, decisions in ADR-022). Each rule is a callable returning a count.

A rule is a pair: `candidates(now)`, the rows due (held rows already excluded), and
`apply(rows, now)`, which deletes or minimises them. `Rule.__call__` runs it in batches of
BATCH_SIZE, each in its own transaction: ids are picked without a lock, then locked with
SKIP LOCKED (a row another transaction holds is left for the next run) and re-checked against
`candidates`, so a hold placed in between still wins. Blobs are deleted only after their
batch commits. Every rule is idempotent: a processed row is no longer a candidate.

Windows are counted from `now` (passed in; tests use a fixed instant). Month windows are
calendar months in Africa/Douala.
"""

import calendar
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Count, Exists, F, Model, OuterRef, Q, QuerySet
from django.db.models.functions import TruncMonth
from django.utils import timezone

from tchekam.ai.product_photo import forget
from tchekam.appeals.models import Appeal, AppealEvidence
from tchekam.checks.models import CheckLog
from tchekam.core.storage import get_object_store
from tchekam.imaging.erase import delete_sightings, delete_unreferenced_images
from tchekam.imaging.models import ImageSighting, WebSearchResult
from tchekam.messaging.models import InboundEvent
from tchekam.reports.keys import reporter_key_for
from tchekam.reports.models import Evidence, PendingNotification, Report, ReportSubject
from tchekam.reputation.service import invalidate_phone

from . import trust
from .hold import held_numbers, held_phones, held_reports, held_users
from .models import CheckLogMonthly, ReporterTrust, TrainingSample

logger = logging.getLogger(__name__)

DOUALA = ZoneInfo("Africa/Douala")
BATCH_SIZE = 200

WEBHOOK_DAYS = 30
GROUP_EVENT_HOURS = 24
NOTIFICATION_DAYS = 30
DRAFT_DAYS = 7
REJECTED_EVIDENCE_DAYS = 90
REJECTED_RECORD_MONTHS = 24
APPROVED_EVIDENCE_MONTHS = 36
CHECK_LOG_MONTHS = 12
SIGHTING_MONTHS = 24
APPEAL_MONTHS = 12


def months_before(moment: datetime, months: int) -> datetime:
    """The same wall-clock time `months` calendar months earlier in Douala (day clamped)."""
    local = timezone.localtime(moment, DOUALA)
    years, index = divmod(local.month - 1 - months, 12)
    year, month = local.year + years, index + 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    return local.replace(year=year, month=month, day=day)


@dataclass(eq=False)
class Rule:
    name: str
    model: type[Model]
    candidates: Callable[[datetime], QuerySet]
    apply: Callable[[QuerySet, datetime], int]

    def __call__(self, now: datetime, dry_run: bool = False) -> int:
        if dry_run:
            return self.candidates(now).count()
        total, last = 0, 0
        while True:
            due = self.candidates(now).filter(pk__gt=last).order_by("pk")
            ids = list(due.values_list("pk", flat=True)[:BATCH_SIZE])
            if not ids:
                return total
            last = ids[-1]  # keyset paging: rows skipped as locked are not picked again
            with transaction.atomic():
                locked = list(
                    self.model.objects.filter(pk__in=ids)
                    .select_for_update(skip_locked=True)
                    .values_list("pk", flat=True)
                )
                if locked:
                    total += self.apply(self.candidates(now).filter(pk__in=locked), now)


# Shared steps ---------------------------------------------------------------------------------


def _delete_blobs_after_commit(keys: Iterable[str]) -> None:
    keys = [k for k in keys if k]
    if keys:
        transaction.on_commit(lambda: delete_blobs(keys))


def delete_blobs(keys: list[str]) -> None:
    store = get_object_store()
    for key in keys:
        try:
            store.delete(key)
        except Exception as exc:  # noqa: BLE001  the rows are gone; a stray blob is harmless
            logger.warning("retention: blob not deleted: %s", type(exc).__name__)


def _invalidate_after_commit(phones: set[str]) -> None:
    if phones:
        transaction.on_commit(lambda: [invalidate_phone(p) for p in phones])


def _subject_phones(report_ids: list[int]) -> set[str]:
    return set(
        ReportSubject.objects.filter(
            report_id__in=report_ids, phone_number__isnull=False
        ).values_list("phone_number__e164", flat=True)
    )


def _subject_images(report_ids: list[int]) -> list[int]:
    return list(
        ReportSubject.objects.filter(report_id__in=report_ids, image__isnull=False).values_list(
            "image_id", flat=True
        )
    )


def _purge_evidence(report_ids: list[int]) -> None:
    """Delete the reports' evidence rows (transcripts, extraction, tamper flags), their blobs
    after commit, and web results no other evidence file shares."""
    rows = Evidence.objects.filter(report_id__in=report_ids)
    keys = list(rows.values_list("object_key", flat=True))
    shas = set(rows.values_list("sha256", flat=True))
    rows.delete()
    still_used = set(Evidence.objects.filter(sha256__in=shas).values_list("sha256", flat=True))
    WebSearchResult.objects.filter(sha256__in=shas - still_used).delete()
    _delete_blobs_after_commit(keys)


def _delete_reports(rows: QuerySet, now: datetime) -> int:
    ids = list(rows.values_list("pk", flat=True))
    if not ids:
        return 0
    phones, images = _subject_phones(ids), _subject_images(ids)
    _purge_evidence(ids)
    deleted = Report.objects.filter(pk__in=ids).delete()[1].get("reports.Report", 0)
    delete_unreferenced_images(images)
    _invalidate_after_commit(phones)
    return deleted


def _count_deleted(rows: QuerySet, now: datetime) -> int:
    return rows.delete()[1].get(rows.model._meta.label, 0)


def _held_events() -> QuerySet:
    """Events sent by (or posted in a group by) a held user or number."""
    phones = held_phones()
    if not phones:
        return InboundEvent.objects.none().values("pk")
    digits = sorted(p.lstrip("+") for p in phones)
    jids = [f"{d}@s.whatsapp.net" for d in digits]
    key = "payload__data__messages__key__"
    sent_by = (
        Q(**{f"{key}cleanedSenderPn__in": digits})
        | Q(**{f"{key}cleanedParticipantPn__in": digits})
        | Q(**{f"{key}remoteJid__in": jids})
        | Q(**{f"{key}participant__in": jids})
    )
    return InboundEvent.objects.filter(sent_by).values("pk")


# Webhooks and notifications ------------------------------------------------------------------


def _webhook_candidates(now: datetime) -> QuerySet:
    return InboundEvent.objects.filter(received_at__lt=now - timedelta(days=WEBHOOK_DAYS)).exclude(
        pk__in=_held_events()
    )


def _group_event_candidates(now: datetime) -> QuerySet:
    scrubbed = InboundEvent.objects.filter(payload__data__messages__scrubbed=True).values("pk")
    return (
        InboundEvent.objects.filter(
            received_at__lt=now - timedelta(hours=GROUP_EVENT_HOURS),
            payload__data__messages__has_key="redacted",
        )
        .exclude(status__in=[InboundEvent.Status.RECEIVED, InboundEvent.Status.PROCESSING])
        .exclude(pk__in=scrubbed)
        .exclude(pk__in=_held_events())
    )


def _scrub(rows: QuerySet, now: datetime) -> int:
    return sum(1 for event in rows if event.scrub_group_payload())


def _notification_candidates(now: datetime) -> QuerySet:
    return (
        PendingNotification.objects.filter(delivered_at__lt=now - timedelta(days=NOTIFICATION_DAYS))
        .exclude(user_id__in=held_users())
        .exclude(report_id__in=held_reports())
    )


# Reports -------------------------------------------------------------------------------------


def _draft_candidates(now: datetime) -> QuerySet:
    return Report.objects.filter(
        status__in=[Report.Status.DRAFT, Report.Status.WITHDRAWN],
        last_activity_at__lt=now - timedelta(days=DRAFT_DAYS),
    ).exclude(pk__in=held_reports())


def _rejected_evidence_candidates(now: datetime) -> QuerySet:
    return Report.objects.filter(
        status=Report.Status.REJECTED,
        minimised_at__isnull=True,
        decided_at__lt=now - timedelta(days=REJECTED_EVIDENCE_DAYS),
    ).exclude(pk__in=held_reports())


def _minimise_rejected(rows: QuerySet, now: datetime) -> int:
    """Keep reporter, status, decision date and the decisions (with their reason)."""
    done = 0
    for report in rows:
        ids = [report.pk]
        phones, images = _subject_phones(ids), _subject_images(ids)
        _purge_evidence(ids)
        ReportSubject.objects.filter(report_id=report.pk).delete()
        Report.objects.filter(pk=report.pk).update(
            subject_phone_keys=sorted(reporter_key_for(p) for p in phones),
            summary_ai="",
            summary_final="",
            amount_xaf=None,
            story_text="",
            ai_extraction={},
            minimised_at=now,
        )
        delete_unreferenced_images(images)
        _invalidate_after_commit(phones)
        done += 1
    return done


def _rejected_record_candidates(now: datetime) -> QuerySet:
    return Report.objects.filter(
        status=Report.Status.REJECTED,
        minimised_at__isnull=False,
        decided_at__lt=months_before(now, REJECTED_RECORD_MONTHS),
    ).exclude(pk__in=held_reports())


def _approved_evidence_candidates(now: datetime) -> QuerySet:
    return Report.objects.filter(
        status=Report.Status.APPROVED,
        minimised_at__isnull=True,
        decided_at__lt=months_before(now, APPROVED_EVIDENCE_MONTHS),
    ).exclude(pk__in=held_reports())


def _merged_evidence_candidates(now: datetime) -> QuerySet:
    """Merged duplicates follow the approved schedule from their merge date (ADR-022)."""
    return Report.objects.filter(
        status=Report.Status.MERGED,
        minimised_at__isnull=True,
        decided_at__lt=months_before(now, APPROVED_EVIDENCE_MONTHS),
    ).exclude(pk__in=held_reports())


def _anonymise_approved(rows: QuerySet, now: datetime) -> int:
    """Keep subjects, status, dates, amount and scam type (statistics) and reporter_key
    (independence). The reporter's trust is stored first, so it survives the dropped link."""
    done = 0
    for report in rows.select_related("reporter"):
        if report.reporter is not None:
            trust.snapshot(report.reporter)
        _purge_evidence([report.pk])
        Report.objects.filter(pk=report.pk).update(
            reporter=None,
            summary_ai="",
            summary_final="",
            story_text="",
            ai_extraction={},
            minimised_at=now,
        )
        _invalidate_after_commit(_subject_phones([report.pk]))
        done += 1
    return done


def _reporter_trust_candidates(now: datetime) -> QuerySet:
    """Snapshots nothing needs any more: no report carries the key (all deleted). Kept while
    any report with the key exists, so an erased reporter never regains weight (ADR-015)."""
    in_use = Report.objects.filter(reporter_key=OuterRef("reporter_key"))
    held_keys = [reporter_key_for(p) for p in held_phones()]
    return ReporterTrust.objects.exclude(Exists(in_use)).exclude(reporter_key__in=held_keys)


# Training samples, check logs, sightings -----------------------------------------------------


def _training_candidates(now: datetime) -> QuerySet:
    return (
        TrainingSample.objects.filter(Q(user__isnull=True) | Q(user__training_opt_in=False))
        .exclude(user_id__in=held_users())
        .exclude(evidence__report_id__in=held_reports())
    )


def delete_training_samples(rows: QuerySet, now: datetime | None = None) -> int:
    keys = list(rows.values_list("audio_key", flat=True))
    deleted = _count_deleted(rows, now)
    _delete_blobs_after_commit(keys)
    return deleted


def _check_log_candidates(now: datetime) -> QuerySet:
    return (
        CheckLog.objects.filter(created_at__lt=months_before(now, CHECK_LOG_MONTHS))
        .exclude(user_id__in=held_users())
        .exclude(subject_ref__in=held_phones())
    )


def _aggregate_check_logs(rows: QuerySet, now: datetime) -> int:
    groups = (
        rows.annotate(month=TruncMonth("created_at", tzinfo=DOUALA))
        .values("subject_ref", "kind", "month")
        .annotate(n=Count("pk"))
        .order_by()
    )
    for group in groups:
        month = timezone.localtime(group["month"], DOUALA).date()
        row, _ = CheckLogMonthly.objects.get_or_create(
            subject_ref=group["subject_ref"], month=month, kind=group["kind"]
        )
        CheckLogMonthly.objects.filter(pk=row.pk).update(count=F("count") + group["n"])
    # Same transaction as the counts: a rerun after a crash never counts a row twice.
    return _count_deleted(rows, now)


def _sighting_candidates(now: datetime) -> QuerySet:
    return (
        ImageSighting.objects.filter(
            context=ImageSighting.Context.GROUP, seen_at__lt=months_before(now, SIGHTING_MONTHS)
        )
        .exclude(phone_number_id__in=held_numbers())
        .exclude(phone_number__e164__in=held_phones())
        .exclude(bot_user_id__in=held_users())
    )


def _delete_sightings(rows: QuerySet, now: datetime) -> int:
    erased = delete_sightings(rows)
    shas = erased.sha256s
    if shas:
        transaction.on_commit(lambda: forget(shas))
    return erased.sightings


# Appeals -------------------------------------------------------------------------------------


def _not_held_appeals(rows: QuerySet) -> QuerySet:
    return rows.exclude(phone_number_id__in=held_numbers()).exclude(appellant_id__in=held_users())


def _appeal_draft_candidates(now: datetime) -> QuerySet:
    return _not_held_appeals(
        Appeal.objects.filter(
            status=Appeal.Status.DRAFT, created_at__lt=now - timedelta(days=DRAFT_DAYS)
        )
    )


def _delete_appeals(rows: QuerySet, now: datetime) -> int:
    ids = list(rows.values_list("pk", flat=True))
    keys = list(
        AppealEvidence.objects.filter(appeal_id__in=ids).values_list("object_key", flat=True)
    )
    deleted = Appeal.objects.filter(pk__in=ids).delete()[1].get("appeals.Appeal", 0)
    _delete_blobs_after_commit(keys)
    return deleted


def _appeal_statement_candidates(now: datetime) -> QuerySet:
    has_evidence = Exists(AppealEvidence.objects.filter(appeal=OuterRef("pk")))
    return _not_held_appeals(
        Appeal.objects.filter(
            status__in=[Appeal.Status.APPROVED, Appeal.Status.REJECTED],
            decided_at__lt=months_before(now, APPEAL_MONTHS),
        ).filter(Q(statement__gt="") | has_evidence)
    )


def _minimise_appeals(rows: QuerySet, now: datetime) -> int:
    """Keep the decision (status, dates, number_acquired_at, the moderator's reason)."""
    ids = list(rows.values_list("pk", flat=True))
    evidence = AppealEvidence.objects.filter(appeal_id__in=ids)
    keys = list(evidence.values_list("object_key", flat=True))
    evidence.delete()
    _delete_blobs_after_commit(keys)
    return Appeal.objects.filter(pk__in=ids).update(statement="")


# Order matters for reports (minimise rejected reports before deleting old minimal records) and
# for trust (prune snapshots only after the report rules deleted what they will).
group_events = Rule("group_events", InboundEvent, _group_event_candidates, _scrub)
webhooks = Rule("webhooks", InboundEvent, _webhook_candidates, _count_deleted)
notifications = Rule("notifications", PendingNotification, _notification_candidates, _count_deleted)
drafts = Rule("drafts", Report, _draft_candidates, _delete_reports)
appeal_drafts = Rule("appeal_drafts", Appeal, _appeal_draft_candidates, _delete_appeals)
rejected_evidence = Rule(
    "rejected_evidence", Report, _rejected_evidence_candidates, _minimise_rejected
)
rejected_records = Rule("rejected_records", Report, _rejected_record_candidates, _delete_reports)
approved_evidence = Rule(
    "approved_evidence", Report, _approved_evidence_candidates, _anonymise_approved
)
merged_evidence = Rule("merged_evidence", Report, _merged_evidence_candidates, _anonymise_approved)
reporter_trust = Rule("reporter_trust", ReporterTrust, _reporter_trust_candidates, _count_deleted)
training_samples = Rule(
    "training_samples", TrainingSample, _training_candidates, delete_training_samples
)
check_logs = Rule("check_logs", CheckLog, _check_log_candidates, _aggregate_check_logs)
group_sightings = Rule("group_sightings", ImageSighting, _sighting_candidates, _delete_sightings)
appeal_statements = Rule(
    "appeal_statements", Appeal, _appeal_statement_candidates, _minimise_appeals
)

RULES: tuple[Rule, ...] = (
    group_events,
    webhooks,
    notifications,
    drafts,
    appeal_drafts,
    rejected_evidence,
    rejected_records,
    approved_evidence,
    merged_evidence,
    reporter_trust,
    training_samples,
    check_logs,
    group_sightings,
    appeal_statements,
)
