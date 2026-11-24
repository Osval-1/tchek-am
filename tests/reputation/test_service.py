import importlib
from datetime import timedelta
from itertools import count

import pytest
from django.core.cache import cache
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.identifiers.models import AccountName, PhoneNumber
from tchekam.reports.models import Evidence, Report, ReportSubject
from tchekam.reputation import appeals_hook
from tchekam.reputation.facts import AppealState, Band
from tchekam.reputation.service import (
    CACHE_TIMEOUT,
    band_for_phone,
    cache_key,
    invalidate_phone,
    invalidate_report,
)

pytestmark = pytest.mark.django_db

TARGET = "+237670000001"
_seq = count(1)


@pytest.fixture(autouse=True)
def _isolate():
    previous = appeals_hook._provider  # restored, so the real provider survives for other tests
    cache.clear()
    appeals_hook.set_provider(None)
    yield
    cache.clear()
    appeals_hook.set_provider(previous)


def user(trust: float = 1.0) -> BotUser:
    return BotUser.objects.create(wa_phone=f"+2376900{next(_seq):05d}", trust_weight=trust)


def phone(e164: str) -> PhoneNumber:
    return PhoneNumber.objects.get_or_create(e164=e164, defaults={"operator": "mtn"})[0]


def make_report(
    status="approved",
    reporter="new",
    e164=TARGET,
    confirmed=True,
    age_days=10,
    submitted_at=None,
    **kw,
) -> Report:
    now = timezone.now()
    r = Report.objects.create(
        reporter=user() if reporter == "new" else reporter,
        status=status,
        submitted_at=submitted_at or now - timedelta(days=age_days + 1),
        decided_at=now - timedelta(days=age_days) if status == "approved" else None,
        **kw,
    )
    ReportSubject.objects.create(
        report=r, phone_number=phone(e164), role="seller", source="ai", confirmed=confirmed
    )
    return r


def name_phone(report: Report, e164: str, confirmed: bool) -> None:
    ReportSubject.objects.create(
        report=report, phone_number=phone(e164), role="payee", source="ai", confirmed=confirmed
    )


def add_evidence(report: Report, sha: str) -> None:
    Evidence.objects.create(
        report=report, object_key=f"k{next(_seq)}", mimetype="image/jpeg", sha256=sha, size_bytes=1
    )


def band(e164=TARGET) -> Band:
    return band_for_phone(e164, now=timezone.now()).band


def test_unknown_number_is_green():
    assert band("+237699999999") == Band.GREEN


def test_three_independent_approved_reporters_is_red():
    for _ in range(3):
        make_report()
    result = band_for_phone(TARGET, now=timezone.now())
    assert result.band == Band.RED
    assert result.approved_count == 3
    assert result.independent_reporters == 3
    assert result.last_report_date == timezone.localdate() - timedelta(days=10)


def test_payment_proof_report_is_red():
    make_report(has_payment_proof=True)
    result = band_for_phone(TARGET, now=timezone.now())
    assert result.band == Band.RED
    assert result.single_report_with_proof is True


def test_approved_report_counts_only_when_its_subject_is_confirmed():
    make_report(confirmed=False, has_payment_proof=True)
    assert band() == Band.GREEN


def test_confirmed_subject_on_another_row_of_the_same_report_counts():
    r = make_report(confirmed=False, has_payment_proof=True)
    name_phone(r, TARGET, confirmed=True)
    assert band() == Band.RED


def test_confirmed_other_number_does_not_make_an_unconfirmed_subject_count():
    r = make_report(confirmed=False, has_payment_proof=True)
    name_phone(r, "+237670000002", confirmed=True)
    assert band() == Band.GREEN
    assert band("+237670000002") == Band.RED


def test_pending_counts_whether_or_not_confirmed():
    make_report(status="pending", confirmed=False)
    make_report(status="needs_info", confirmed=True)
    result = band_for_phone(TARGET, now=timezone.now())
    assert result.band == Band.YELLOW
    assert result.pending_count == 2


def test_rejected_merged_withdrawn_and_draft_never_count():
    for status in ("rejected", "merged", "withdrawn", "draft"):
        make_report(status=status, has_payment_proof=True)
    assert band() == Band.GREEN


def test_reports_about_other_numbers_do_not_count():
    make_report(e164="+237670000002", has_payment_proof=True)
    assert band() == Band.GREEN


def test_non_phone_subjects_are_ignored():
    r = make_report()
    ReportSubject.objects.create(
        report=r,
        account_name=AccountName.objects.create(normalized="jean", display_raw="Jean"),
        role="payee",
        source="ai",
        confirmed=True,
    )
    make_report()
    make_report()
    assert band() == Band.RED


def test_old_approved_reports_decay():
    for _ in range(3):
        make_report(age_days=400)
    assert band() == Band.ORANGE
    Report.objects.update(decided_at=timezone.now() - timedelta(days=800))
    assert band() == Band.GREEN


def test_incident_date_ages_the_report():
    make_report(has_payment_proof=True, incident_date=timezone.localdate() - timedelta(days=400))
    assert band() == Band.ORANGE


def test_reporter_named_on_another_report_is_dependent_even_if_unconfirmed():
    # Confirmation decides whether a report counts against a number, not whether a mention
    # of another reporter's number is grounds to doubt their independence.
    reporters = [user(), user(), user()]
    reports = [make_report(reporter=u) for u in reporters]
    assert band() == Band.RED
    name_phone(reports[0], reporters[1].wa_phone, confirmed=False)
    assert band() == Band.ORANGE


def test_pending_reports_use_all_phone_subjects():
    # Pending reports do not reach the independence count, but their facts carry every
    # phone subject; this pins the query path (and catches crashes on it).
    r = make_report(status="pending", confirmed=False)
    name_phone(r, "+237670000009", confirmed=False)
    assert band() == Band.YELLOW


def test_shared_evidence_within_minutes_links_reporters():
    at = timezone.now() - timedelta(days=5)
    reports = [make_report(submitted_at=at + timedelta(minutes=i)) for i in range(3)]
    add_evidence(reports[0], "a" * 64)
    add_evidence(reports[1], "b" * 64)
    add_evidence(reports[2], "c" * 64)
    assert band() == Band.RED
    add_evidence(reports[2], "a" * 64)
    assert band() == Band.ORANGE


def test_similar_final_summaries_within_minutes_link_reporters():
    at = timezone.now() - timedelta(days=5)
    text = "Paid 40000 FCFA by Orange Money for a laptop, then he stopped answering."
    for i, summary in enumerate([text, text + ".", "Fake shoes."]):
        make_report(submitted_at=at + timedelta(minutes=i), summary_final=summary)
    assert band() == Band.ORANGE


def test_same_reporter_counts_once():
    u = user()
    for _ in range(3):
        make_report(reporter=u)
    assert band() == Band.ORANGE


def test_low_trust_reporter_is_excluded():
    make_report()
    make_report()
    make_report(reporter=user(trust=0.2))
    assert band() == Band.ORANGE


SEVERITY = {Band.GREEN: 0, Band.YELLOW: 1, Band.ORANGE: 2, Band.RED: 3}


def test_erased_reporter_never_becomes_more_reporters():
    u = user()
    for _ in range(3):
        make_report(reporter=u)
    before = band_for_phone(TARGET, now=timezone.now())
    u.delete()  # erasure: reports keep their pseudonymous reporter_key
    assert Report.objects.filter(reporter__isnull=True).count() == 3
    after = band_for_phone(TARGET, now=timezone.now())
    assert before.independent_reporters == 1
    assert after.independent_reporters == 0  # erased = trust 0: no longer counts on its own
    assert before.band == after.band == Band.ORANGE


def test_erasing_a_named_reporter_does_not_split_their_cluster():
    # B names A's number; A's report names D's number; C is unrelated. One cluster + C = 2.
    a, b, c, d = user(), user(), user(), user()
    report_a = make_report(reporter=a)
    name_phone(report_a, d.wa_phone, confirmed=False)
    report_b = make_report(reporter=b)
    name_phone(report_b, a.wa_phone, confirmed=False)
    make_report(reporter=c)
    make_report(reporter=d)
    before = band_for_phone(TARGET, now=timezone.now())
    assert (before.band, before.independent_reporters) == (Band.ORANGE, 2)
    a.delete()  # B's mention of A still matches A's key, so B stays linked to A and D
    after = band_for_phone(TARGET, now=timezone.now())
    assert (after.band, after.independent_reporters) == (Band.ORANGE, 2)


def test_erasing_a_low_trust_reporter_with_proof_does_not_worsen_the_band():
    u = user(trust=0.1)
    make_report(reporter=u, has_payment_proof=True)
    make_report()
    before = band()
    u.delete()
    assert SEVERITY[band()] <= SEVERITY[before]
    assert before == Band.ORANGE


def test_erasing_a_trusted_reporter_with_proof_lowers_red():
    u = user()
    make_report(reporter=u, has_payment_proof=True)
    assert band() == Band.RED
    u.delete()
    assert band() == Band.ORANGE  # an erased reporter cannot carry the proof route alone


def test_reports_that_never_had_a_reporter_do_not_count_as_reporters():
    for _ in range(3):
        make_report(reporter=None)
    result = band_for_phone(TARGET, now=timezone.now())
    assert result.independent_reporters == 0
    assert result.band == Band.ORANGE


def test_low_trust_reporters_payment_proof_is_not_red():
    make_report(reporter=user(trust=0.2), has_payment_proof=True)
    assert band() == Band.ORANGE


def test_appeal_provider_excludes_reports_before_acquisition():
    today = timezone.localdate()
    for _ in range(3):
        make_report(incident_date=today - timedelta(days=60))
    make_report(status="pending", submitted_at=timezone.now() - timedelta(days=60))
    seen = []

    def provider(e164):
        seen.append(e164)
        return AppealState(under_appeal=True, number_acquired_at=today - timedelta(days=30))

    appeals_hook.set_provider(provider)
    result = band_for_phone(TARGET, now=timezone.now())
    assert seen == [TARGET]
    assert result.band == Band.GREEN
    assert result.pending_count == 0
    assert result.under_appeal is True


def test_default_appeal_provider_reports_no_appeal():
    assert appeals_hook.get_appeal_state(TARGET) == AppealState(False, None)


# Caching


def test_result_is_cached_for_an_hour_until_invalidated():
    assert band_for_phone(TARGET).band == Band.GREEN
    make_report(has_payment_proof=True)
    assert band_for_phone(TARGET).band == Band.GREEN  # served from cache
    invalidate_phone(TARGET)
    assert band_for_phone(TARGET).band == Band.RED
    assert CACHE_TIMEOUT == 3600
    assert cache_key(TARGET) == "reputation:phone:+237670000001"
    assert cache.get(cache_key(TARGET)).band == Band.RED


def test_cache_entry_expires(monkeypatch):
    calls = []
    real_set = cache.set
    monkeypatch.setattr(cache, "set", lambda k, v, t: calls.append((k, t)) or real_set(k, v, t))
    band_for_phone(TARGET)
    assert calls == [(cache_key(TARGET), CACHE_TIMEOUT)]


def test_explicit_now_bypasses_the_cache():
    band_for_phone(TARGET)
    make_report(has_payment_proof=True)
    assert band_for_phone(TARGET, now=timezone.now()).band == Band.RED
    assert cache.get(cache_key(TARGET)).band == Band.GREEN  # untouched


def test_cache_works_on_the_shared_database_backend():
    """Base/prod settings use DatabaseCache so web and worker see the same invalidations."""
    from django.conf import settings
    from django.db import connection
    from django.test import override_settings

    from tchekam.settings import base

    assert base.CACHES["default"]["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"
    assert settings.CACHES["default"]["BACKEND"].endswith("LocMemCache")  # tests stay fast
    migration = importlib.import_module("tchekam.reputation.migrations.0001_cache_table")
    with override_settings(CACHES=base.CACHES):
        migration.create_cache_table(None, connection.schema_editor())
        assert base.CACHES["default"]["LOCATION"] in connection.introspection.table_names()
        make_report(has_payment_proof=True)
        assert band_for_phone(TARGET).band == Band.RED
        Report.objects.update(has_payment_proof=False)
        assert band_for_phone(TARGET).band == Band.RED  # cached row, pickled BandResult
        invalidate_phone(TARGET)
        assert band_for_phone(TARGET).band == Band.ORANGE


def test_invalidate_report_clears_every_phone_on_the_report():
    other = "+237670000002"
    r = make_report(status="pending")
    name_phone(r, other, confirmed=False)
    band_for_phone(TARGET)
    band_for_phone(other)
    band_for_phone("+237670000003")
    invalidate_report(r)
    assert cache.get(cache_key(TARGET)) is None
    assert cache.get(cache_key(other)) is None
    assert cache.get(cache_key("+237670000003")) is not None


def test_status_change_invalidates_the_band_on_commit(django_capture_on_commit_callbacks):
    r = make_report(status="pending", has_payment_proof=True)
    assert band_for_phone(TARGET).band == Band.YELLOW
    with django_capture_on_commit_callbacks(execute=True):
        r.transition("approved")
        assert band_for_phone(TARGET).band == Band.YELLOW  # not yet committed
    assert band_for_phone(TARGET).band == Band.RED


def test_merge_invalidates_the_merged_reports_numbers(django_capture_on_commit_callbacks):
    target = make_report(status="pending", e164="+237670000002")
    r = make_report(status="pending")
    assert band_for_phone(TARGET).band == Band.YELLOW
    with django_capture_on_commit_callbacks(execute=True):
        r.merge_into(target)
    assert band_for_phone(TARGET).band == Band.GREEN
