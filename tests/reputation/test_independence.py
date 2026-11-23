from dataclasses import replace
from datetime import timedelta
from difflib import SequenceMatcher

import pytest

from tchekam.reputation.independence import MIN_TRUST_WEIGHT, independent_reporters

from .helpers import approved, days_ago, phone_of

T0 = days_ago(10)
SUMMARY = "He took 50000 FCFA by MoMo for a phone and then blocked me on WhatsApp."
SHA = {"evidence_sha256s": frozenset({"f" * 64})}


def _reporter(n: int, **kw):
    """Approved report n by reporter n (own number phone_of(n), key key_of(phone_of(n)))."""
    return approved(n, reporter_id=n, **kw)


def _names(*reporters: int) -> dict:
    return {"subject_phones": frozenset(phone_of(n) for n in reporters)}


def _erased(f):
    """What the service builds once the BotUser is deleted: no phone, trust 0, key kept."""
    return replace(f, reporter_phone=None, reporter_trust=0.0)


def test_no_reports_means_no_reporters():
    assert independent_reporters([]) == 0


def test_distinct_unrelated_reporters_are_independent():
    assert independent_reporters([approved(1), approved(2), approved(3)]) == 3


def test_same_reporter_key_is_one_reporter():
    assert independent_reporters([approved(i, reporter_id=7) for i in (1, 2, 3)]) == 1


def test_erased_reporter_keeps_one_identity_through_the_key():
    facts = [approved(i, reporter_id=7, reporter_phone=None) for i in (1, 2, 3)]
    assert independent_reporters(facts) == 1


def test_reports_with_no_reporter_at_all_are_each_their_own_node():
    facts = [approved(i, reporter_id=None) for i in (1, 2)]
    assert independent_reporters(facts) == 2


def test_blank_key_with_a_live_phone_falls_back_to_the_phone():
    facts = [approved(i, reporter_id=7, reporter_key="") for i in (1, 2)]
    assert independent_reporters(facts) == 1


def test_fallback_nodes_cannot_collide_with_real_keys():
    facts = [
        approved(1, reporter_key="2"),  # a key equal to report 2's id
        approved(2, reporter_id=None),  # falls back to its report id
        approved(3, reporter_key=phone_of(4)),  # a key equal to reporter 4's phone
        approved(4, reporter_id=4, reporter_key=""),  # falls back to its phone
    ]
    assert independent_reporters(facts) == 4


def test_report_naming_the_other_reporters_number_makes_them_dependent():
    assert independent_reporters([_reporter(1, **_names(2)), _reporter(2)]) == 1
    assert independent_reporters([_reporter(2), _reporter(1, **_names(2))]) == 1


def test_naming_survives_the_named_reporters_erasure():
    # Via subject_keys: the named reporter's key is still on file after the phone is gone.
    assert independent_reporters([_reporter(1, **_names(2)), _erased(_reporter(2))]) == 1
    assert independent_reporters([_erased(_reporter(2)), _reporter(1, **_names(2))]) == 1


def test_naming_by_phone_alone_still_links():
    a = _reporter(1, subject_keys=frozenset(), **_names(2))
    assert independent_reporters([a, _reporter(2)]) == 1


def test_naming_an_unrelated_number_does_not_link():
    other = {"subject_phones": frozenset({"+237699999999"})}
    assert independent_reporters([_reporter(1, **other), _reporter(2, **other)]) == 2


def test_reporter_without_phone_or_key_cannot_be_named():
    a = approved(1, reporter_id=None)
    b = approved(2, subject_phones=frozenset({"+237699999999"}))
    assert independent_reporters([a, b]) == 2


def _pair(gap: timedelta, a_kw: dict, b_kw: dict):
    return [approved(1, submitted_at=T0, **a_kw), approved(2, submitted_at=T0 + gap, **b_kw)]


@pytest.mark.parametrize(
    ("gap", "a_kw", "b_kw", "expected"),
    [
        pytest.param(timedelta(minutes=10), SHA, SHA, 1, id="shared sha, 10 min apart"),
        pytest.param(timedelta(minutes=-10), SHA, SHA, 1, id="shared sha, 10 min before"),
        pytest.param(timedelta(minutes=10, seconds=1), SHA, SHA, 2, id="shared sha, over 10 min"),
        pytest.param(
            timedelta(minutes=3),
            SHA,
            {"evidence_sha256s": frozenset({"e" * 64})},
            2,
            id="different sha within window",
        ),
        pytest.param(
            timedelta(minutes=3),
            {"summary": SUMMARY},
            {"summary": SUMMARY + "!"},
            1,
            id="near-identical text within window",
        ),
        pytest.param(
            timedelta(minutes=30),
            {"summary": SUMMARY},
            {"summary": SUMMARY},
            2,
            id="identical text outside window",
        ),
        pytest.param(
            timedelta(minutes=3),
            {"summary": SUMMARY},
            {"summary": "Fake shoes, never came."},
            2,
            id="different text within window",
        ),
        pytest.param(
            timedelta(minutes=3), {"summary": ""}, {"summary": ""}, 2, id="both summaries empty"
        ),
        pytest.param(
            timedelta(minutes=3), {"summary": SUMMARY}, {"summary": ""}, 2, id="one summary empty"
        ),
        pytest.param(
            timedelta(minutes=3), {"summary": ""}, {"summary": SUMMARY}, 2, id="other empty"
        ),
        pytest.param(timedelta(minutes=3), {}, {}, 2, id="nothing shared within window"),
    ],
)
def test_near_identical_submissions(gap, a_kw, b_kw, expected):
    assert independent_reporters(_pair(gap, a_kw, b_kw)) == expected


def test_text_similarity_threshold_is_point_nine():
    base = "a" * 90 + "b" * 10
    at = "a" * 90 + "c" * 10
    below = "a" * 89 + "c" * 11
    assert SequenceMatcher(None, base, at).ratio() == 0.9
    assert SequenceMatcher(None, base, below).ratio() < 0.9
    near = timedelta(minutes=1)
    assert independent_reporters(_pair(near, {"summary": base}, {"summary": at})) == 1
    assert independent_reporters(_pair(near, {"summary": base}, {"summary": below})) == 2


@pytest.mark.parametrize("missing", ["a", "b"])
def test_missing_submission_time_never_links_by_evidence(missing):
    a = approved(1, submitted_at=None if missing == "a" else T0, **SHA)
    b = approved(2, submitted_at=None if missing == "b" else T0, **SHA)
    assert independent_reporters([a, b]) == 2


def test_dependency_is_transitive():
    # A names B's number; B and C sent the same screenshot within minutes. A~B, B~C, so 1.
    a = _reporter(1, **_names(2))
    b = _reporter(2, submitted_at=T0, **SHA)
    c = _reporter(3, submitted_at=T0 + timedelta(minutes=5), **SHA)
    assert independent_reporters([a, b, c]) == 1
    assert independent_reporters([c, a, b, _reporter(4)]) == 2


def test_same_reporter_links_through_any_of_their_reports():
    # Reporter 1 filed two reports; only the second shares evidence with reporter 2.
    a1 = approved(1, reporter_id=1, submitted_at=days_ago(100))
    a2 = approved(2, reporter_id=1, submitted_at=T0, **SHA)
    b = approved(3, reporter_id=2, submitted_at=T0 + timedelta(minutes=1), **SHA)
    assert independent_reporters([a1, a2, b]) == 1


def test_low_trust_reporters_are_not_counted_on_their_own():
    assert MIN_TRUST_WEIGHT == 0.3
    facts = [approved(1), approved(2, reporter_trust=0.29), approved(3, reporter_trust=0.3)]
    assert independent_reporters(facts) == 2


def test_cluster_counts_once_if_any_member_is_trusted():
    a = _reporter(1, reporter_trust=0.1, **_names(2))
    assert independent_reporters([a, _reporter(2)]) == 1
    assert independent_reporters([a, _reporter(2, reporter_trust=0.0)]) == 0


def test_low_trust_reporters_still_link_others():
    # B (low trust) bridges A and C: they stay one cluster, as they would with B trusted.
    a = _reporter(1, **_names(2))
    b = _reporter(2, reporter_trust=0.1, **_names(3))
    c = _reporter(3)
    assert independent_reporters([a, b, c]) == 1


@pytest.mark.parametrize("l_trust", [1.0, 0.1])
def test_reviewer_case_low_trust_bridge_does_not_split_a_cluster(l_trust):
    # A names L's number; B sent L's screenshot within minutes; C is unrelated.
    low = _reporter(2, reporter_trust=l_trust, submitted_at=T0, **SHA)
    a = _reporter(1, **_names(2))
    b = _reporter(3, submitted_at=T0 + timedelta(minutes=4), **SHA)
    c = _reporter(4)
    assert independent_reporters([a, low, b, c]) == 2


def test_erased_bridge_does_not_split_a_cluster():
    # B names A; A names D. Erasing A must keep B, A and D in one cluster.
    a = _reporter(1, **_names(4))
    b = _reporter(2, **_names(1))
    d = _reporter(4)
    assert independent_reporters([a, b, d]) == 1
    assert independent_reporters([_erased(a), b, d]) == 1
