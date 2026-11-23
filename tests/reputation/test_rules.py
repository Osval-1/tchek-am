from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from tchekam.reputation.facts import NO_APPEAL, AppealState, Band
from tchekam.reputation.rules import FULL_WEIGHT_DAYS, VISIBLE_DAYS, compute_band

from .helpers import NOW, approved, date_ago, days_ago, report

GREEN, YELLOW, ORANGE, RED = Band.GREEN, Band.YELLOW, Band.ORANGE, Band.RED
MONTH = 30

BAND_CASES = [
    # (id, facts, expected band)
    ("no reports", [], GREEN),
    ("rejected only", [report(1, "rejected"), report(2, "rejected")], GREEN),
    ("merged only", [report(1, "merged")], GREEN),
    ("withdrawn and draft only", [report(1, "withdrawn"), report(2, "draft")], GREEN),
    ("pending only", [report(1, "pending")], YELLOW),
    ("needs_info only", [report(1, "needs_info")], YELLOW),
    ("rejected with proof never counts", [report(1, "rejected", has_payment_proof=True)], GREEN),
    ("merged with proof never counts", [report(1, "merged", has_payment_proof=True)], GREEN),
    ("one approved, no proof", [approved(1)], ORANGE),
    ("2 independent reporters", [approved(1), approved(2)], ORANGE),
    ("3 independent reporters", [approved(1), approved(2), approved(3)], RED),
    ("1 report with proof", [approved(1, has_payment_proof=True)], RED),
    (
        "3 reporters all 13 months old",
        [approved(i, age_days=13 * MONTH) for i in (1, 2, 3)],
        ORANGE,
    ),
    ("approved 25 months old is ignored", [approved(1, age_days=25 * MONTH)], GREEN),
    (
        "approved 25 months old plus pending",
        [approved(1, age_days=25 * MONTH), report(2, "pending")],
        YELLOW,
    ),
    (
        "3 independent, 25 months old, are ignored",
        [approved(i, age_days=25 * MONTH) for i in (1, 2, 3)],
        GREEN,
    ),
    (
        "proof but 13 months old",
        [approved(1, age_days=13 * MONTH, has_payment_proof=True)],
        ORANGE,
    ),
    (
        "proof 13 months old plus a recent approved report",
        [approved(1, age_days=13 * MONTH, has_payment_proof=True), approved(2)],
        RED,
    ),
    (
        "proof 25 months old plus a recent approved report",
        [approved(1, age_days=25 * MONTH, has_payment_proof=True), approved(2)],
        ORANGE,
    ),
    (
        "3 independent, only one under 12 months",
        [approved(1, 13 * MONTH), approved(2, 14 * MONTH), approved(3, 2 * MONTH)],
        RED,
    ),
    (
        "3 independent, one of them 25 months old",
        [approved(1), approved(2), approved(3, age_days=25 * MONTH)],
        ORANGE,
    ),
    ("one reporter, 3 reports", [approved(i, reporter_id=7) for i in (1, 2, 3)], ORANGE),
    (
        "3 reporters, one under the trust floor",
        [approved(1), approved(2), approved(3, reporter_trust=0.29)],
        ORANGE,
    ),
    (
        "3 reporters at exactly the trust floor",
        [approved(i, reporter_trust=0.3) for i in (1, 2, 3)],
        RED,
    ),
    (
        "proof from a reporter under the trust floor is not enough",
        [approved(1, has_payment_proof=True, reporter_trust=0.29)],
        ORANGE,
    ),
    (
        "proof from a reporter at the trust floor",
        [approved(1, has_payment_proof=True, reporter_trust=0.3)],
        RED,
    ),
    (
        "low-trust proof plus a trusted recent report is not enough",
        [approved(1, has_payment_proof=True, reporter_trust=0.1), approved(2), approved(3)],
        ORANGE,
    ),
    (
        "3 independent at 400 days plus a low-trust recent report stays orange",
        [approved(i, 400) for i in (1, 2, 3)] + [approved(4, 10, reporter_trust=0.1)],
        ORANGE,
    ),
    (
        "3 independent at 400 days plus a trusted recent report",
        [approved(i, 400) for i in (1, 2, 3)] + [approved(4, 10)],
        RED,
    ),
    (
        "proof from an erased reporter (trust 0) is not enough",
        [approved(1, has_payment_proof=True, reporter_phone=None, reporter_trust=0.0)],
        ORANGE,
    ),
    ("approved beats pending", [approved(1), report(2, "pending")], ORANGE),
    (
        "full weight at 364 days",
        [approved(1, FULL_WEIGHT_DAYS - 1, has_payment_proof=True)],
        RED,
    ),
    (
        "reduced weight at 365 days",
        [approved(1, FULL_WEIGHT_DAYS, has_payment_proof=True)],
        ORANGE,
    ),
    ("visible at 729 days", [approved(1, VISIBLE_DAYS - 1)], ORANGE),
    ("hidden at 730 days", [approved(1, VISIBLE_DAYS)], GREEN),
    (
        "age from incident_date when earlier than decision",
        [approved(1, age_days=10, incident_date=date_ago(VISIBLE_DAYS))],
        GREEN,
    ),
    (
        "incident 13 months ago caps a fresh decision at orange",
        [approved(1, age_days=10, incident_date=date_ago(13 * MONTH), has_payment_proof=True)],
        ORANGE,
    ),
    (
        "decision used when earlier than incident_date",
        [approved(1, age_days=VISIBLE_DAYS, incident_date=date_ago(5))],
        GREEN,
    ),
    (
        "approved without decided_at ages from incident_date",
        [approved(1, decided_at=None, incident_date=date_ago(5), has_payment_proof=True)],
        RED,
    ),
    (
        "approved with no age reference at all is not counted",
        [approved(1, decided_at=None, has_payment_proof=True)],
        GREEN,
    ),
]


@pytest.mark.parametrize(
    ("facts", "expected"), [c[1:] for c in BAND_CASES], ids=[c[0] for c in BAND_CASES]
)
def test_band(facts, expected):
    assert compute_band(facts, NOW, NO_APPEAL).band == expected


def test_red_from_three_reporters_reports_counts():
    result = compute_band([approved(1, 40), approved(2, 10), approved(3, 100)], NOW, NO_APPEAL)
    assert result.band == RED
    assert result.approved_count == 3
    assert result.independent_reporters == 3
    assert result.pending_count == 0
    assert result.last_report_date == date_ago(10)
    assert result.single_report_with_proof is False
    assert result.under_appeal is False


def test_red_from_payment_proof_is_flagged_single_report():
    result = compute_band([approved(1, has_payment_proof=True)], NOW, NO_APPEAL)
    assert result.band == RED
    assert result.single_report_with_proof is True
    assert result.independent_reporters == 1


def test_red_with_proof_and_three_reporters_is_not_single_report():
    facts = [approved(1, has_payment_proof=True), approved(2), approved(3)]
    assert compute_band(facts, NOW, NO_APPEAL).single_report_with_proof is False


def test_orange_is_never_flagged_single_report():
    result = compute_band([approved(1, 13 * MONTH, has_payment_proof=True)], NOW, NO_APPEAL)
    assert result.single_report_with_proof is False


def test_counts_ignore_hidden_and_non_counting_reports():
    facts = [
        approved(1, 10),
        approved(2, 25 * MONTH),
        report(3, "pending"),
        report(4, "needs_info"),
        report(5, "rejected"),
        report(6, "draft"),
    ]
    result = compute_band(facts, NOW, NO_APPEAL)
    assert result.band == ORANGE
    assert result.approved_count == 1
    assert result.pending_count == 2
    assert result.last_report_date == date_ago(10)


def test_last_report_date_uses_the_age_reference():
    facts = [approved(1, age_days=5, incident_date=date_ago(50))]
    assert compute_band(facts, NOW, NO_APPEAL).last_report_date == date_ago(50)


def test_green_and_yellow_have_no_last_report_date():
    assert compute_band([], NOW, NO_APPEAL).last_report_date is None
    assert compute_band([report(1, "pending")], NOW, NO_APPEAL).last_report_date is None


def test_red_decays_to_orange_after_12_months_without_new_reports():
    facts = [approved(1, 0), approved(2, 0), approved(3, 0)]
    assert compute_band(facts, NOW, NO_APPEAL).band == RED
    assert compute_band(facts, NOW + timedelta(days=FULL_WEIGHT_DAYS - 1), NO_APPEAL).band == RED
    assert compute_band(facts, NOW + timedelta(days=FULL_WEIGHT_DAYS), NO_APPEAL).band == ORANGE
    assert compute_band(facts, NOW + timedelta(days=VISIBLE_DAYS), NO_APPEAL).band == GREEN


def test_proof_red_decays_to_orange_after_12_months():
    facts = [approved(1, 0, has_payment_proof=True)]
    assert compute_band(facts, NOW, NO_APPEAL).band == RED
    assert compute_band(facts, NOW + timedelta(days=FULL_WEIGHT_DAYS), NO_APPEAL).band == ORANGE


def test_age_uses_the_calendar_day_in_nows_timezone():
    douala = ZoneInfo("Africa/Douala")  # UTC+1, no DST
    now = NOW.replace(hour=0, minute=30).astimezone(douala)  # 2026-11-23 01:30 local
    # 2025-11-23 23:30 UTC is 2025-11-24 00:30 in Douala: 364 local days ago, so still red.
    # Read as a UTC calendar date it would be 365 days (orange): the day must be local.
    decided = (NOW - timedelta(days=FULL_WEIGHT_DAYS)).replace(hour=23, minute=30)
    facts = [approved(1, decided_at=decided, has_payment_proof=True)]
    assert compute_band(facts, now, NO_APPEAL).band == RED
    an_hour_earlier = [approved(1, decided_at=decided - timedelta(hours=1), has_payment_proof=True)]
    assert compute_band(an_hour_earlier, now, NO_APPEAL).band == ORANGE  # 22:30 UTC = 23:30 local


# Appeals: "this number is new to me".


def test_appeal_excludes_reports_with_incident_before_acquisition():
    facts = [approved(i, 10, incident_date=date_ago(100)) for i in (1, 2, 3)]
    appeal = AppealState(under_appeal=False, number_acquired_at=date_ago(50))
    assert compute_band(facts, NOW, appeal).band == GREEN


def test_appeal_keeps_reports_on_or_after_acquisition():
    facts = [approved(i, 10, incident_date=date_ago(50)) for i in (1, 2, 3)]
    appeal = AppealState(under_appeal=False, number_acquired_at=date_ago(50))
    assert compute_band(facts, NOW, appeal).band == RED


def test_appeal_falls_back_to_submission_date_when_no_incident_date():
    facts = [
        approved(1, 10, submitted_at=days_ago(100)),
        approved(2, 10, submitted_at=days_ago(20)),
    ]
    appeal = AppealState(under_appeal=False, number_acquired_at=date_ago(50))
    result = compute_band(facts, NOW, appeal)
    assert result.band == ORANGE
    assert result.approved_count == 1


def test_appeal_excludes_pending_reports_too():
    facts = [report(1, "pending", submitted_at=days_ago(100))]
    appeal = AppealState(under_appeal=False, number_acquired_at=date_ago(50))
    result = compute_band(facts, NOW, appeal)
    assert result.band == GREEN
    assert result.pending_count == 0


def test_appeal_excludes_if_submission_predates_acquisition_despite_later_incident():
    facts = [approved(1, 10, incident_date=date_ago(20), submitted_at=days_ago(100))]
    appeal = AppealState(under_appeal=False, number_acquired_at=date_ago(50))
    assert compute_band(facts, NOW, appeal).band == GREEN


def test_appeal_excludes_if_incident_predates_acquisition_despite_later_submission():
    facts = [approved(1, 10, incident_date=date_ago(100), submitted_at=days_ago(20))]
    appeal = AppealState(under_appeal=False, number_acquired_at=date_ago(50))
    assert compute_band(facts, NOW, appeal).band == GREEN


def test_appeal_keeps_reports_with_no_date_at_all():
    facts = [report(1, "pending", submitted_at=None)]
    appeal = AppealState(under_appeal=False, number_acquired_at=date_ago(50))
    assert compute_band(facts, NOW, appeal).band == YELLOW


def test_under_appeal_passes_through():
    appeal = AppealState(under_appeal=True, number_acquired_at=None)
    result = compute_band([approved(1, has_payment_proof=True)], NOW, appeal)
    assert result.band == RED
    assert result.under_appeal is True


def test_appeal_defaults_to_no_appeal():
    assert compute_band([approved(1)], NOW).under_appeal is False


def test_counted_report_ids_exclude_decayed_pre_acquisition_and_non_approved():
    counted = approved(1, 10, incident_date=date_ago(20))
    decayed = approved(2, 10, incident_date=date_ago(VISIBLE_DAYS + 5))
    old_owner = approved(3, 10, incident_date=date_ago(100))
    pending = report(4, "pending")
    appeal = AppealState(under_appeal=False, number_acquired_at=date_ago(50))

    result = compute_band([counted, decayed, old_owner, pending], NOW, appeal)

    assert result.counted_report_ids == frozenset({1})
