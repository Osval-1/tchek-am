import pytest
from django.db import IntegrityError, transaction

from tchekam.conversations.models import BotUser
from tchekam.identifiers.models import AccountName, PhoneNumber
from tchekam.imaging.models import Image
from tchekam.reports.models import Evidence, Report, ReportLink, ReportSubject

pytestmark = pytest.mark.django_db


@pytest.fixture
def report():
    user = BotUser.objects.create(wa_phone="+237600000001")
    return Report.objects.create(reporter=user)


@pytest.fixture
def parts():
    return (
        PhoneNumber.objects.create(e164="+237670000001", operator="mtn"),
        AccountName.objects.create(normalized="jean", display_raw="Jean"),
        Image.objects.create(sha256="a" * 64),
    )


def subject(report, **kw):
    return ReportSubject(report=report, role="seller", source="ai", **kw)


def ordered_pair(a, b):
    return (a, b) if a.pk < b.pk else (b, a)


def test_subject_with_exactly_one_target_is_accepted(report, parts):
    phone, name, image = parts
    for kw in ({"phone_number": phone}, {"account_name": name}, {"image": image}):
        subject(report, **kw).save()
    assert ReportSubject.objects.count() == 3


def test_subject_with_no_target_is_rejected(report):
    with pytest.raises(IntegrityError), transaction.atomic():
        subject(report).save()


def test_subject_with_two_targets_is_rejected(report, parts):
    phone, name, image = parts
    for kw in (
        {"phone_number": phone, "account_name": name},
        {"phone_number": phone, "image": image},
        {"account_name": name, "image": image},
        {"phone_number": phone, "account_name": name, "image": image},
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            subject(report, **kw).save()


def test_link_orders_the_pair_and_is_idempotent(report):
    other = Report.objects.create(reporter=report.reporter)
    lo, hi = ordered_pair(report, other)

    link = ReportLink.link(hi, lo, ReportLink.Reason.SAME_NUMBER, 0.9)
    again = ReportLink.link(lo, hi, ReportLink.Reason.SAME_NUMBER, 0.9)

    assert link.pk == again.pk
    assert link.report_a_id < link.report_b_id
    assert ReportLink.objects.count() == 1


def test_link_unsorted_pair_rejected_by_db(report):
    other = Report.objects.create(reporter=report.reporter)
    lo, hi = ordered_pair(report, other)
    with pytest.raises(IntegrityError), transaction.atomic():
        ReportLink.objects.create(report_a=hi, report_b=lo, reason="same_name", score=1)


def test_link_to_self_rejected(report):
    with pytest.raises(ValueError):
        ReportLink.link(report, report, "same_name", 1.0)


def test_str_methods_leak_no_pii(report, parts):
    phone, _, _ = parts
    s = subject(report, phone_number=phone)
    s.save()
    ev = Evidence.objects.create(
        report=report, object_key="k", mimetype="image/png", sha256="b" * 64, size_bytes=1
    )
    for obj in (report, s, ev):
        assert "+237" not in str(obj)
        assert "Jean" not in str(obj)
