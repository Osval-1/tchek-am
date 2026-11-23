"""Properties of the band rules.

1. One reporter, however many reports they file, cannot produce red without proof.
2. Lowering a reporter's trust, or erasing a reporter, never makes a band worse.
"""

from dataclasses import replace
from datetime import timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from tchekam.reputation.facts import NO_APPEAL, AppealState, Band, ReportFacts
from tchekam.reputation.independence import MIN_TRUST_WEIGHT
from tchekam.reputation.rules import FULL_WEIGHT_DAYS, compute_band

from .helpers import NOW, key_of, phone_of

PHONES = ["+237670000001", "+237690000002", "+237650000003"]
STATUSES = ["approved", "pending", "needs_info", "rejected", "merged", "withdrawn", "draft"]
ANY_STATUS = st.sampled_from(STATUSES)


@st.composite
def one_reporters_reports(draw, statuses=ANY_STATUS):
    # The key survives erasure; the phone does not. Same person either way.
    reporter_key = draw(st.text(alphabet="0123456789abcdef", min_size=64, max_size=64))
    reporter_phone = draw(st.none() | st.just("+237600000009"))
    reports = []
    for i in range(draw(st.integers(min_value=1, max_value=25))):
        age = draw(st.integers(min_value=0, max_value=FULL_WEIGHT_DAYS - 1))
        decided_at = NOW - timedelta(days=age)
        reports.append(
            ReportFacts(
                report_id=i + 1,
                status=draw(statuses),
                reporter_key=reporter_key,
                reporter_phone=reporter_phone,
                reporter_trust=draw(st.floats(min_value=0, max_value=1)),
                submitted_at=NOW - timedelta(minutes=draw(st.integers(0, 60 * 24 * 400))),
                decided_at=decided_at,
                incident_date=draw(st.none() | st.just(decided_at.date())),
                has_payment_proof=False,
                subject_phones=draw(st.frozensets(st.sampled_from(PHONES))),
                evidence_sha256s=draw(st.frozensets(st.sampled_from(["a" * 64, "b" * 64]))),
                summary=draw(st.text(max_size=40)),
            )
        )
    return reports


@given(one_reporters_reports(statuses=st.just("approved")))
def test_one_reporter_approved_without_proof_is_orange_never_red(reports):
    result = compute_band(reports, NOW, NO_APPEAL)
    assert result.band == Band.ORANGE
    assert result.independent_reporters <= 1


@given(one_reporters_reports(), st.booleans())
def test_one_reporter_without_proof_is_never_red_in_any_band(reports, under_appeal):
    appeal = AppealState(under_appeal=under_appeal, number_acquired_at=None)
    result = compute_band(reports, NOW, appeal)
    assert result.band in {Band.GREEN, Band.YELLOW, Band.ORANGE}
    assert result.single_report_with_proof is False


# Invariant: trust and erasure can only ever lower a band.

SEVERITY = {Band.GREEN: 0, Band.YELLOW: 1, Band.ORANGE: 2, Band.RED: 3}
REPORTERS = [1, 2, 3, 4, 5]
TARGET = "+237670000001"
SUBJECT_PHONES = [TARGET] + [phone_of(n) for n in REPORTERS]
SUMMARIES = ["", "Paid 30000 by MoMo, no phone came.", "Paid 30000 by MoMo, no phone came!", "x"]


@st.composite
def fact_sets(draw):
    """Reports from a small pool of reporters who name each other, share evidence, etc.

    Facts are built the way the service builds them: the key is derived from the reporter's
    number and subject_keys from subject_phones, so naming links survive erasure.
    """
    trust = {n: draw(st.floats(min_value=0, max_value=1)) for n in REPORTERS}
    facts = []
    for i in range(draw(st.integers(min_value=0, max_value=12))):
        reporter = draw(st.sampled_from([*REPORTERS, None]))  # None: never had a reporter
        # Biased toward reports that count (approved, recent) so clusters actually form.
        age = draw(
            st.integers(min_value=0, max_value=364) | st.integers(min_value=0, max_value=800)
        )
        decided_at = NOW - timedelta(days=age)
        incident_age = draw(st.sampled_from([None] * 3 + [age, 400, 800]))
        subjects = draw(st.frozensets(st.sampled_from(SUBJECT_PHONES)))
        own = None if reporter is None else phone_of(reporter)
        facts.append(
            ReportFacts(
                report_id=i + 1,
                status=draw(st.sampled_from(["approved"] * 6 + STATUSES)),
                reporter_key=key_of(own) if own else "",
                reporter_phone=own,
                reporter_trust=0.0 if reporter is None else trust[reporter],
                # Two clusters of submission times so the 10-minute rule fires often.
                submitted_at=NOW
                - timedelta(days=draw(st.sampled_from([5, 400])), minutes=draw(st.integers(0, 15))),
                decided_at=draw(st.sampled_from([decided_at] * 9 + [None])),
                incident_date=None
                if incident_age is None
                else (NOW - timedelta(incident_age)).date(),
                has_payment_proof=draw(st.booleans()),
                subject_phones=subjects,
                subject_keys=frozenset(key_of(p) for p in subjects),
                evidence_sha256s=draw(st.frozensets(st.sampled_from(["a" * 64, "b" * 64]))),
                summary=draw(st.sampled_from(SUMMARIES)),
            )
        )
    acquired = draw(st.sampled_from([None] * 3 + [2, 300]))
    appeal = AppealState(
        under_appeal=draw(st.booleans()),
        number_acquired_at=None if acquired is None else (NOW - timedelta(acquired)).date(),
    )
    return facts, appeal


def _apply(facts, reporter, change):
    key = key_of(phone_of(reporter))
    return [change(f) if f.reporter_key == key else f for f in facts]


@settings(max_examples=500)
@given(
    fact_sets(),
    st.sampled_from(REPORTERS),
    st.floats(min_value=0, max_value=MIN_TRUST_WEIGHT, exclude_max=True),
)
def test_lowering_a_reporters_trust_never_worsens_the_band(case, reporter, low):
    facts, appeal = case
    before = compute_band(facts, NOW, appeal)
    after = compute_band(
        _apply(facts, reporter, lambda f: replace(f, reporter_trust=low)), NOW, appeal
    )
    assert SEVERITY[after.band] <= SEVERITY[before.band]
    assert after.independent_reporters <= before.independent_reporters


@settings(max_examples=500)
@given(fact_sets(), st.sampled_from(REPORTERS))
def test_erasing_a_reporter_never_worsens_the_band(case, reporter):
    facts, appeal = case
    before = compute_band(facts, NOW, appeal)
    erase = lambda f: replace(f, reporter_phone=None, reporter_trust=0.0)  # noqa: E731
    after = compute_band(_apply(facts, reporter, erase), NOW, appeal)
    assert SEVERITY[after.band] <= SEVERITY[before.band]
    assert after.independent_reporters <= before.independent_reporters
