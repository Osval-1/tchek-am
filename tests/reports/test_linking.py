from difflib import SequenceMatcher

import pytest
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.i18n import t
from tchekam.identifiers.models import get_or_create_account_name, get_or_create_phone
from tchekam.imaging.models import Image
from tchekam.reports.linking import TEXT_SIMILARITY, link_report, reused_from_other_reporter
from tchekam.reports.models import Evidence, Report, ReportLink, ReportSubject
from tchekam.reports.scoring import refresh_evidence_score
from tchekam.reports.tasks import DUPLICATE_EVIDENCE, _keep, _Stored, link

pytestmark = pytest.mark.django_db

PHONE = "+237677123456"
_seq = iter(range(1, 10_000))


def make(status="pending", summary="", **kw) -> Report:
    n = next(_seq)
    reporter = kw.pop("reporter", None) or BotUser.objects.create(wa_phone=f"+2376500{n:05d}")
    return Report.objects.create(
        reporter=reporter, status=status, summary_ai=summary, submitted_at=timezone.now(), **kw
    )


def phone(report, number=PHONE, confirmed=False, source="ai"):
    return ReportSubject.objects.create(
        report=report, phone_number=get_or_create_phone(number), role="seller",
        source=source, confirmed=confirmed,
    )  # fmt: skip


def evidence(report, sha="a" * 64):
    n = next(_seq)
    return Evidence.objects.create(
        report=report, kind="chat", object_key=f"k{n}", mimetype="image/png",
        sha256=sha, size_bytes=1,
    )  # fmt: skip


def pairs():
    return sorted(
        (link.report_a_id, link.report_b_id, link.reason) for link in ReportLink.objects.all()
    )


def test_same_number_links_ai_and_confirmed_subjects():
    a, b, c = make(), make(status="approved"), make()
    phone(a)
    phone(b, confirmed=True, source="moderator")
    phone(c, "+237677999999")

    link_report(a)

    assert pairs() == [(a.pk, b.pk, "same_number")]


def test_same_number_ignores_unconfirmed_non_ai_subjects():
    a, b = make(), make()
    phone(a)
    phone(b, source="user", confirmed=False)

    link_report(a)

    assert not ReportLink.objects.exists()


def test_same_name():
    a, b, c = make(), make(), make()
    for report, name in ((a, "Jean Dupont"), (b, "JEAN  dupont"), (c, "Paul Biya")):
        ReportSubject.objects.create(
            report=report, account_name=get_or_create_account_name(name, "momo"),
            role="payee", source="ai",
        )  # fmt: skip

    link_report(a)

    assert pairs() == [(a.pk, b.pk, "same_name")]


def test_same_image_by_evidence_sha256():
    a, b, c = make(), make(), make()
    evidence(a, "1" * 64)
    evidence(b, "1" * 64)
    evidence(c, "2" * 64)

    link_report(a)

    assert pairs() == [(a.pk, b.pk, "same_image")]


def test_same_image_by_product_image_subject():
    a, b = make(), make()
    evidence(a, "3" * 64)
    ReportSubject.objects.create(
        report=b, image=Image.objects.create(sha256="3" * 64), role="product", source="ai"
    )

    link_report(a)

    assert pairs() == [(a.pk, b.pk, "same_image")]


def test_similar_text_links_close_summaries_only():
    base = "The buyer paid for a phone that was never delivered to him."
    a = make(summary=base)
    close = make(summary=base.replace("phone", "phones"))
    make(summary="Completely different story about a rental deposit and a landlord.")

    link_report(a)

    assert pairs() == [(a.pk, close.pk, "similar_text")]
    assert ReportLink.objects.get().score >= TEXT_SIMILARITY


@pytest.mark.parametrize(
    ("other", "linked"),
    [
        ("abcdefghijklmnopqrst", True),  # identical
        ("abcdefghijklmnopqrXX", True),  # 18/20 shared: 0.9
        ("abcdefghijklmnoXXXXX", False),  # 15/20: 0.75
    ],
)
def test_similar_text_threshold(other, linked):
    mine = "abcdefghijklmnopqrst"
    assert (SequenceMatcher(None, mine, other).ratio() >= TEXT_SIMILARITY) == linked
    a = make(summary=mine)
    make(summary=other)

    link_report(a)

    assert ReportLink.objects.exists() == linked


def test_neutral_placeholder_summaries_never_link():
    text = t("report.summary_neutral", "en")
    make(summary=text)
    a = make(summary=text)

    link_report(a)

    assert not ReportLink.objects.exists()


def test_summary_final_wins_over_ai_summary():
    a = make(summary="x", summary_final="The seller took the money and vanished completely.")
    b = make(summary="y", summary_final="The seller took the money and vanished completely!")

    link_report(a)

    assert pairs() == [(a.pk, b.pk, "similar_text")]


@pytest.mark.parametrize("status", ["draft", "rejected", "withdrawn", "merged"])
def test_non_live_reports_are_not_linked(status):
    a, other = make(), make(status=status)
    phone(a)
    phone(other)

    link_report(a)

    assert not ReportLink.objects.exists()


def test_non_live_source_report_links_nothing():
    a, b = make(status="rejected"), make()
    phone(a)
    phone(b)

    assert link_report(a) == 0
    assert not ReportLink.objects.exists()


def test_links_are_symmetric_and_deduplicated():
    a, b = make(), make()
    phone(a)
    phone(b)

    link_report(a)
    link_report(b)
    link_report(a)

    assert pairs() == [(min(a.pk, b.pk), max(a.pk, b.pk), "same_number")]


def test_one_pair_can_be_linked_for_several_reasons():
    a, b = make(), make()
    for r in (a, b):
        phone(r)
        evidence(r)

    link_report(a)

    assert {p[2] for p in pairs()} == {"same_number", "same_image"}
    assert all(p[0] < p[1] for p in pairs())


def test_link_task_scores_links_and_ignores_missing_reports():
    a, b = make(), make()
    phone(a)
    phone(b)
    evidence(a)

    link(report_id=a.pk)
    link(report_id=999_999)

    assert pairs() == [(a.pk, b.pk, "same_number")]
    assert Report.objects.get(pk=a.pk).evidence_score == pytest.approx(0.3)


# Duplicate evidence ---------------------------------------------------------------------------


def test_reuse_by_another_reporter_is_detected_but_not_by_the_same_reporter():
    first = make()
    evidence(first, "9" * 64)
    own_again = evidence(make(reporter=first.reporter), "9" * 64)
    assert not reused_from_other_reporter(own_again)

    other = evidence(make(), "9" * 64)

    assert reused_from_other_reporter(other)


def test_withdrawn_reports_do_not_count_as_a_source():
    evidence(make(status="withdrawn"), "8" * 64)
    assert not reused_from_other_reporter(evidence(make(), "8" * 64))


def test_ingest_flags_duplicate_evidence_across_reporters_only():
    first = make()
    evidence(first, "7" * 64)
    other, same = make(status="draft"), make(status="draft", reporter=first.reporter)

    def ingest(report, mid):
        stored = _Stored(key=f"k-{mid}", kind="chat", mimetype="image/png", sha256="7" * 64, size=1)
        assert _keep(report.pk, mid, stored) == "report.ack"
        return Evidence.objects.get(report=report, source_message_id=mid)

    assert (
        ingest(same, "m2").tamper_flags == []
    )  # ingested first: nothing from another reporter yet
    assert ingest(other, "m1").tamper_flags == [DUPLICATE_EVIDENCE]
    # A chat screenshot is worth 0.3; the flag costs 0.2.
    assert refresh_evidence_score(other) == pytest.approx(0.1)
