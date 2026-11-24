"""One test per rule: an object just inside its window is kept, one just outside is processed."""

from datetime import date, datetime, timedelta

import pytest
from django.core.cache import cache

from tchekam.appeals.models import Appeal, AppealEvidence
from tchekam.checks.models import CheckLog
from tchekam.imaging.models import Image, ImageSighting, WebSearchResult
from tchekam.messaging.models import InboundEvent
from tchekam.reports.keys import reporter_key_for
from tchekam.reports.models import Evidence, ModerationDecision, PendingNotification, Report
from tchekam.reputation.service import band_for_phone, cache_key
from tchekam.retention import rules
from tchekam.retention.models import CheckLogMonthly, ReporterTrust

from .builders import (
    DOUALA,
    MINUTE,
    NOW,
    appeal,
    check_log,
    event,
    evidence,
    group_sighting,
    phone,
    report,
    set_time,
    user,
)

pytestmark = pytest.mark.django_db

DAY = timedelta(days=1)


# Webhooks ------------------------------------------------------------------------------------


def test_webhooks_older_than_30_days_are_deleted(run):
    old = event(NOW - 30 * DAY - MINUTE)
    kept = event(NOW - 30 * DAY + MINUTE)

    assert run(rules.webhooks) == 1

    assert list(InboundEvent.objects.values_list("pk", flat=True)) == [kept.pk]
    assert not InboundEvent.objects.filter(pk=old.pk).exists()


def test_group_events_are_scrubbed_after_24_hours(run):
    old = event(NOW - 24 * timedelta(hours=1) - MINUTE, group=True, sender="237670000077")
    fresh = event(NOW - 24 * timedelta(hours=1) + MINUTE, group=True)
    private = event(NOW - 2 * DAY)

    assert run(rules.group_events) == 1

    old.refresh_from_db()
    stored = old.payload["data"]["messages"]
    assert "237670000077" not in str(old.payload)
    assert stored["message"] == {}
    assert stored["scrubbed"] is True
    assert stored["key"]["id"] == old.message_id
    fresh.refresh_from_db()
    assert "cleanedParticipantPn" in fresh.payload["data"]["messages"]["key"]
    private.refresh_from_db()
    assert private.payload["data"]["messages"]["message"] == {"conversation": "hello"}
    assert run(rules.group_events) == 0  # idempotent


def test_group_events_still_being_processed_are_not_scrubbed(run):
    pending = event(NOW - 2 * DAY, group=True, status=InboundEvent.Status.RECEIVED)

    assert run(rules.group_events) == 0
    pending.refresh_from_db()
    assert pending.payload["data"]["messages"]["message"]


def _notification(delivered_at):
    from django.contrib.auth import get_user_model

    r = report("rejected")
    mod = get_user_model().objects.create_user(f"mod-{r.pk}")
    decision = ModerationDecision.objects.create(report=r, moderator=mod, action="reject")
    return PendingNotification.objects.create(
        user=r.reporter, report=r, decision=decision, delivered_at=delivered_at
    )


def test_delivered_notifications_older_than_30_days_are_deleted(run):
    old = _notification(NOW - 30 * DAY - MINUTE)
    kept = _notification(NOW - 30 * DAY + MINUTE)
    undelivered = _notification(None)

    assert run(rules.notifications) == 1

    remaining = set(PendingNotification.objects.values_list("pk", flat=True))
    assert remaining == {kept.pk, undelivered.pk}
    assert old.pk not in remaining


# Drafts --------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["draft", "withdrawn"])
def test_abandoned_drafts_are_deleted_with_their_blobs(object_store, status, run):
    old = report(status, last_activity_at=NOW - 7 * DAY - MINUTE)
    voice = evidence(old, Evidence.Kind.VOICE)
    WebSearchResult.objects.create(sha256=voice.sha256, matches=[])
    keys = list(old.evidence.values_list("object_key", flat=True))
    kept = report(status, last_activity_at=NOW - 7 * DAY + MINUTE)
    kept_keys = list(kept.evidence.values_list("object_key", flat=True))

    assert run(rules.drafts) == 1

    assert not Report.objects.filter(pk=old.pk).exists()
    assert not Evidence.objects.filter(report_id=old.pk).exists()
    assert not any(object_store.exists(k) for k in keys)
    assert not WebSearchResult.objects.filter(sha256=voice.sha256).exists()
    assert Report.objects.get(pk=kept.pk).story_text
    assert all(object_store.exists(k) for k in kept_keys)


def test_submitted_reports_are_never_treated_as_drafts(run):
    r = report("pending", last_activity_at=NOW - 400 * DAY)

    assert run(rules.drafts) == 0
    assert Report.objects.filter(pk=r.pk).exists()


def test_appeal_drafts_older_than_7_days_are_deleted_with_their_blobs(object_store, run):
    old = appeal("draft")
    set_time(Appeal, old.pk, created_at=NOW - 7 * DAY - MINUTE)
    old_keys = list(old.evidence.values_list("object_key", flat=True))
    kept = appeal("draft")
    set_time(Appeal, kept.pk, created_at=NOW - 7 * DAY + MINUTE)
    submitted = appeal("open")
    set_time(Appeal, submitted.pk, created_at=NOW - 30 * DAY)

    assert run(rules.appeal_drafts) == 1

    assert set(Appeal.objects.values_list("pk", flat=True)) == {kept.pk, submitted.pk}
    assert not AppealEvidence.objects.filter(appeal_id=old.pk).exists()
    assert not any(object_store.exists(k) for k in old_keys)


# Rejected reports ----------------------------------------------------------------------------


def test_rejected_reports_keep_a_minimal_record_after_90_days(object_store, run):
    seller = phone("+237690000123")
    old = report("rejected", seller=seller, decided_at=NOW - 90 * DAY - MINUTE)
    voice = evidence(old, Evidence.Kind.VOICE)
    keys = list(old.evidence.values_list("object_key", flat=True))
    kept = report("rejected", decided_at=NOW - 90 * DAY + MINUTE)

    assert run(rules.rejected_evidence) == 1

    old.refresh_from_db()
    assert old.status == "rejected" and old.reporter_id is not None and old.decided_at
    assert (old.story_text, old.summary_ai, old.summary_final) == ("", "", "")
    assert old.ai_extraction == {} and old.amount_xaf is None
    assert old.subject_phone_keys == [reporter_key_for("+237690000123")]
    assert not old.subjects.exists()
    assert not Evidence.objects.filter(pk=voice.pk).exists()  # with its transcript
    assert not any(object_store.exists(k) for k in keys)
    assert old.minimised_at == NOW
    kept.refresh_from_db()
    assert kept.story_text and kept.evidence.exists() and kept.subjects.exists()
    assert run(rules.rejected_evidence) == 0  # idempotent


def test_web_results_shared_with_live_evidence_survive(run):
    old = report("rejected", decided_at=NOW - 100 * DAY)
    sha = old.evidence.get().sha256
    live = report("pending")
    evidence(live, sha256=sha)
    WebSearchResult.objects.create(sha256=sha, matches=[])

    run(rules.rejected_evidence)

    assert WebSearchResult.objects.filter(sha256=sha).exists()


def test_rejected_images_no_longer_referenced_are_deleted(object_store, run):
    from tchekam.reports.models import ReportSubject

    old = report("rejected", decided_at=NOW - 100 * DAY)
    thumb = object_store.put("thumbnails/x", b"j", "image/jpeg")
    image = Image.objects.create(sha256="f" * 64, thumbnail_key=thumb)
    ReportSubject.objects.create(report=old, image=image, role="product", source="ai")

    run(rules.rejected_evidence)

    assert not Image.objects.filter(pk=image.pk).exists()
    assert not object_store.exists(thumb)


def test_rejected_minimal_records_are_deleted_after_24_months(run):
    old = report("rejected", decided_at=datetime(2024, 11, 24, 2, 0, tzinfo=DOUALA) - MINUTE)
    kept = report("rejected", decided_at=datetime(2024, 11, 24, 2, 0, tzinfo=DOUALA) + MINUTE)
    run(rules.rejected_evidence)

    assert run(rules.rejected_records) == 1

    assert set(Report.objects.values_list("pk", flat=True)) == {kept.pk}
    assert old.pk not in set(Report.objects.values_list("pk", flat=True))


def test_a_minimised_rejected_report_cannot_be_reopened(run):
    from tchekam.reports.transitions import InvalidTransition

    old = report("rejected", decided_at=NOW - 100 * DAY)
    run(rules.rejected_evidence)
    old.refresh_from_db()

    with pytest.raises(InvalidTransition):
        old.transition("pending")


# Approved reports ----------------------------------------------------------------------------

THIRTY_SIX_MONTHS = datetime(2023, 11, 24, 2, 0, tzinfo=DOUALA)


def test_approved_reports_are_anonymised_after_36_months(object_store, run):
    reporter = user(trust_weight=0.2)
    old = report("approved", reporter, decided_at=THIRTY_SIX_MONTHS - MINUTE)
    voice = evidence(old, Evidence.Kind.VOICE)
    keys = list(old.evidence.values_list("object_key", flat=True))
    kept = report("approved", decided_at=THIRTY_SIX_MONTHS + MINUTE)

    assert run(rules.approved_evidence) == 1

    old.refresh_from_db()
    assert old.reporter_id is None
    assert old.reporter_key == reporter_key_for(reporter.wa_phone)  # independence survives
    assert (old.story_text, old.summary_ai, old.summary_final) == ("", "", "")
    assert old.ai_extraction == {}
    assert old.amount_xaf == 25000 and old.decided_at and old.status == "approved"
    assert old.subjects.count() == 1  # statistics
    assert not Evidence.objects.filter(pk=voice.pk).exists()
    assert not any(object_store.exists(k) for k in keys)
    assert ReporterTrust.objects.get(reporter_key=old.reporter_key).trust_weight == 0.2
    kept.refresh_from_db()
    assert kept.reporter_id and kept.evidence.exists()
    assert run(rules.approved_evidence) == 0


def test_anonymising_does_not_change_the_band_and_clears_its_cache(run):
    seller = phone("+237690000555")
    old = report("approved", seller=seller, decided_at=THIRTY_SIX_MONTHS - MINUTE)
    before = band_for_phone(seller.e164, now=NOW)
    band_for_phone(seller.e164)  # cached
    assert cache.get(cache_key(seller.e164)) is not None

    run(rules.approved_evidence)

    assert band_for_phone(seller.e164, now=NOW) == before
    assert cache.get(cache_key(seller.e164)) is None
    assert old.pk


def test_anonymising_old_reports_keeps_the_reporters_trust(run):
    from tchekam.reports.weighting import _counts

    reporter = user()
    report("approved", reporter, decided_at=THIRTY_SIX_MONTHS - DAY)

    run(rules.approved_evidence)

    assert _counts(reporter) == (1, 0)


# Training samples ----------------------------------------------------------------------------


def test_training_samples_of_withdrawn_or_erased_users_are_deleted(object_store, run):
    from tchekam.retention.models import TrainingSample

    def sample(owner):
        key = object_store.put(f"training/{owner and owner.pk}", b"ogg", "audio/ogg")
        return TrainingSample.objects.create(user=owner, audio_key=key, mimetype="audio/ogg")

    consenting = sample(user(training_opt_in=True))
    withdrawn = sample(user(training_opt_in=False))
    orphan = sample(None)

    assert run(rules.training_samples) == 2

    assert list(TrainingSample.objects.values_list("pk", flat=True)) == [consenting.pk]
    assert not object_store.exists(withdrawn.audio_key)
    assert not object_store.exists(orphan.audio_key)
    assert object_store.exists(consenting.audio_key)


# Check logs ----------------------------------------------------------------------------------

TWELVE_MONTHS = datetime(2025, 11, 24, 2, 0, tzinfo=DOUALA)


def test_check_logs_older_than_12_months_are_aggregated_then_deleted(run):
    check_log(TWELVE_MONTHS - MINUTE)
    check_log(TWELVE_MONTHS - 2 * DAY)
    check_log(datetime(2025, 10, 31, 23, 30, tzinfo=DOUALA))  # Douala month, not UTC
    check_log(TWELVE_MONTHS - MINUTE, kind="image", subject_ref="ab" * 32)
    kept = check_log(TWELVE_MONTHS + MINUTE)

    assert run(rules.check_logs) == 4

    assert list(CheckLog.objects.values_list("pk", flat=True)) == [kept.pk]
    monthly = {(m.subject_ref, m.month, m.kind): m.count for m in CheckLogMonthly.objects.all()}
    assert monthly == {
        ("+237690000001", date(2025, 11, 1), "number"): 2,
        ("+237690000001", date(2025, 10, 1), "number"): 1,
        ("ab" * 32, date(2025, 11, 1), "image"): 1,
    }


def test_check_log_aggregation_adds_to_existing_months(run):
    check_log(TWELVE_MONTHS - MINUTE)
    run(rules.check_logs)
    check_log(TWELVE_MONTHS - DAY)

    run(rules.check_logs)
    run(rules.check_logs)

    assert CheckLogMonthly.objects.get().count == 2


# Group sightings -----------------------------------------------------------------------------

TWENTY_FOUR_MONTHS = datetime(2024, 11, 24, 2, 0, tzinfo=DOUALA)


def test_group_sightings_older_than_24_months_are_deleted_with_orphaned_images(object_store, run):
    old = group_sighting(TWENTY_FOUR_MONTHS - MINUTE)
    thumb = old.image.thumbnail_key
    kept = group_sighting(TWENTY_FOUR_MONTHS + MINUTE)
    shared_old = group_sighting(TWENTY_FOUR_MONTHS - DAY, image=kept.image)

    assert run(rules.group_sightings) == 2

    assert list(ImageSighting.objects.values_list("pk", flat=True)) == [kept.pk]
    assert not Image.objects.filter(pk=old.image_id).exists()
    assert not object_store.exists(thumb)
    assert Image.objects.filter(pk=shared_old.image_id).exists()


def test_images_referenced_by_reports_survive_sighting_deletion(object_store, run):
    from tchekam.reports.models import ReportSubject

    old = group_sighting(TWENTY_FOUR_MONTHS - DAY)
    r = report("approved")
    ReportSubject.objects.create(report=r, image=old.image, role="product", source="ai")

    assert run(rules.group_sightings) == 1

    assert Image.objects.filter(pk=old.image_id).exists()
    assert object_store.exists(old.image.thumbnail_key)


# Appeals -------------------------------------------------------------------------------------


def test_decided_appeals_lose_statement_and_evidence_after_12_months(object_store, run):
    old = appeal("rejected", decided_at=TWELVE_MONTHS - MINUTE, reason="not convincing")
    keys = list(old.evidence.values_list("object_key", flat=True))
    kept = appeal("approved", decided_at=TWELVE_MONTHS + MINUTE)
    open_ = appeal("open", submitted_at=NOW - 800 * DAY)

    assert run(rules.appeal_statements) == 1

    old.refresh_from_db()
    assert old.statement == "" and not old.evidence.exists()
    assert old.status == "rejected" and old.decided_at and old.reason == "not convincing"
    assert not any(object_store.exists(k) for k in keys)
    assert Appeal.objects.get(pk=kept.pk).statement
    assert Appeal.objects.get(pk=open_.pk).statement
    assert run(rules.appeal_statements) == 0


def test_merged_reports_are_anonymised_36_months_after_the_merge(object_store, run):
    old = report("merged", decided_at=THIRTY_SIX_MONTHS - MINUTE)
    keys = list(old.evidence.values_list("object_key", flat=True))
    kept = report("merged", decided_at=THIRTY_SIX_MONTHS + MINUTE)

    assert run(rules.merged_evidence) == 1

    old.refresh_from_db()
    assert old.reporter_id is None and old.story_text == "" and old.ai_extraction == {}
    assert old.subjects.count() == 1 and old.status == "merged" and old.minimised_at == NOW
    assert not old.evidence.exists()
    assert not any(object_store.exists(k) for k in keys)
    kept.refresh_from_db()
    assert kept.reporter_id and kept.evidence.exists()
    assert run(rules.merged_evidence) == 0


def test_trust_snapshots_are_pruned_once_no_report_carries_the_key(run):
    gone = ReporterTrust.objects.create(reporter_key="gone", trust_weight=0.2)
    r = report("rejected")
    used = ReporterTrust.objects.create(reporter_key=r.reporter_key, trust_weight=0.2)

    assert run(rules.reporter_trust) == 1

    assert list(ReporterTrust.objects.all()) == [used]
    assert not ReporterTrust.objects.filter(pk=gone.pk).exists()
