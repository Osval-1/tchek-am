from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from tchekam.checks.models import CheckLog
from tchekam.moderation.priority import priority_score, queue_rows

pytestmark = pytest.mark.django_db


def checks(ref, n, age=timedelta(days=1)):
    for _ in range(n):
        log = CheckLog.objects.create(kind="number", subject_ref=ref, result_band="yellow")
        CheckLog.objects.filter(pk=log.pk).update(created_at=timezone.now() - age)


def test_priority_formula():
    assert priority_score(0, 0.0, "") == pytest.approx(0.1)
    assert priority_score(4, 0.5, "momo_fraud") == pytest.approx(5 * 0.6 * 3)
    assert priority_score(1, 0.4, "advance_fee") == pytest.approx(2 * 0.5 * 2.5)
    assert priority_score(1, 0.4, "fake_product") == pytest.approx(2 * 0.5 * 2)
    assert priority_score(1, 0.4, "other") == pytest.approx(2 * 0.5)


def test_queue_orders_by_priority_with_three_seeded_reports(make_report):
    a = make_report(phone="+237677000001", scam_type="other", evidence_score=0.9)  # 1*1.0*1 = 1.0
    b = make_report(phone="+237677000002", scam_type="momo_fraud", evidence_score=0.2)
    c = make_report(phone="+237677000003", scam_type="fake_product", evidence_score=0.4)
    checks("+237677000002", 1)  # b: 2 * 0.3 * 3 = 1.8
    checks("+237677000003", 3)  # c: 4 * 0.5 * 2 = 4.0
    checks("+237677000001", 5, age=timedelta(days=8))  # outside the 7-day window: ignored
    make_report(phone="+237677000004", status="approved")  # not in the queue

    rows = queue_rows()

    assert [r.report.pk for r in rows] == [c.pk, b.pk, a.pk]
    assert [r.checks for r in rows] == [3, 1, 0]
    assert [round(r.priority, 2) for r in rows] == [4.0, 1.8, 1.0]


def test_ties_go_to_the_oldest_submission(make_report):
    newer = make_report(phone="+237677000011", submitted_ago=timedelta(hours=1))
    older = make_report(phone="+237677000012", submitted_ago=timedelta(hours=5))
    assert [r.report.pk for r in queue_rows()] == [older.pk, newer.pk]


def test_needs_info_reports_are_listed_and_other_statuses_are_not(make_report):
    ni = make_report(status="needs_info", phone="+237677000021")
    for status in ("draft", "approved", "rejected", "merged", "withdrawn"):
        make_report(status=status, phone=None)
    assert [r.report.pk for r in queue_rows()] == [ni.pk]


def test_queue_page_lists_columns_and_never_the_reporter_phone(staff_client, make_report):
    report = make_report(reporter_phone="+237699888777", amount_xaf=25000, files=2)
    checks("+237677123456", 2)

    resp = staff_client.get(reverse("moderation:queue"))

    html = resp.content.decode()
    assert report.reference in html
    assert "seen in 2 checks" in html
    assert "25000" in html
    assert reverse("moderation:review", args=[report.pk]) in html
    assert "699888777" not in html
    assert "evidence/secret" not in html
