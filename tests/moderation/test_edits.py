from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from tchekam.core.models import AuditLog
from tchekam.reports.models import Report, ReportSubject
from tchekam.reputation.service import band_for_phone

from .conftest import SELLER, post_data, warm

pytestmark = pytest.mark.django_db


def save_url(report):
    return reverse("moderation:save", args=[report.pk])


def test_confirming_a_subject_changes_band_immediately(make_report, post):
    # A pending report is yellow; approved + confirmed makes it orange. Warm the cache first.
    report = make_report(status="approved")
    assert warm().band == "green"  # approved but unconfirmed subject does not count
    subject = report.subjects.get()

    resp = post(save_url(report), post_data(report, **{f"confirmed_{subject.pk}": "on"}))

    assert resp.status_code == 302
    assert band_for_phone(SELLER).band == "orange"


def test_payment_proof_flips_single_report_orange_to_red(make_report, post):
    report = make_report(status="approved", confirmed=True)
    assert warm().band == "orange"

    post(save_url(report), post_data(report, has_payment_proof="on"))

    report.refresh_from_db()
    assert report.has_payment_proof
    assert band_for_phone(SELLER).band == "red"


def test_incident_date_change_invalidates_band(make_report, post):
    old = timezone.localdate() - timedelta(days=30)
    report = make_report(status="approved", confirmed=True, proof=True, incident_date=old)
    assert warm().band == "red"
    ancient = timezone.localdate() - timedelta(days=800)

    post(save_url(report), post_data(report, incident_date=ancient.isoformat()))

    assert band_for_phone(SELLER).band != "red"


def test_removing_a_subject_invalidates_the_removed_number(make_report, post):
    report = make_report(status="approved", confirmed=True)
    assert warm().band == "orange"
    subject = report.subjects.get()

    post(save_url(report), post_data(report, **{f"remove_{subject.pk}": "on"}))

    assert not report.subjects.exists()
    assert band_for_phone(SELLER).band == "green"


def test_adding_a_phone_makes_a_confirmed_moderator_seller(make_report, post):
    report = make_report(phone=None)
    assert warm("+237655111222").band == "green"

    post(save_url(report), post_data(report, add_phone="655 11 12 22"))

    s = report.subjects.get()
    assert (s.phone_number.e164, s.role, s.source, s.confirmed) == (
        "+237655111222", "seller", "moderator", True,
    )  # fmt: skip
    assert band_for_phone("+237655111222").band == "yellow"


def test_adding_a_payee_name(make_report, post):
    report = make_report()

    post(save_url(report), post_data(report, add_name="Jean <b>Dupont", add_name_provider="momo"))

    s = report.subjects.exclude(account_name=None).get()
    assert (s.role, s.source, s.confirmed, s.account_name.provider) == (
        "payee", "moderator", True, "momo",
    )  # fmt: skip


def test_invalid_phone_future_date_and_bad_amount_change_nothing(make_report, post):
    report = make_report()
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    for bad in (
        {"add_phone": "12345"},
        {"incident_date": tomorrow},
        {"amount_xaf": "0"},
        {"amount_xaf": "-5"},
        {"scam_type": "bogus"},
    ):
        before = Report.objects.filter(pk=report.pk).values().get()
        resp = post(save_url(report), post_data(report, **bad))
        assert resp.status_code == 302
        assert Report.objects.filter(pk=report.pk).values().get() == before, bad
    assert not AuditLog.objects.filter(action="report.edit").exists()


def test_edit_fields_are_saved_and_audit_has_field_names_only(make_report, post):
    report = make_report()
    data = post_data(
        report, scam_type="advance_fee", amount_xaf="40000", summary_final=" Final text ",
        incident_date="2026-11-01", add_phone="677999888",
    )  # fmt: skip

    post(save_url(report), data)

    report.refresh_from_db()
    assert (report.scam_type, report.amount_xaf, report.summary_final) == (
        "advance_fee", 40000, "Final text",
    )  # fmt: skip
    entry = AuditLog.objects.get(action="report.edit")
    assert set(entry.metadata["fields"]) == {
        "scam_type", "amount_xaf", "summary_final", "incident_date", "subjects.added",
    }  # fmt: skip
    assert "677999888" not in str(entry.metadata) and "Final" not in str(entry.metadata)


@pytest.mark.parametrize("status", ["rejected", "merged"])
def test_terminal_reports_cannot_be_edited(make_report, post, status):
    report = make_report(status=status)
    data = post_data(report, scam_type="other", add_phone="677999888")

    resp = post(save_url(report), data)

    assert resp.status_code == 302
    report.refresh_from_db()
    assert report.scam_type == "momo_fraud"
    assert report.subjects.count() == 1


def test_stale_token_refuses_the_save(make_report, post):
    report = make_report()
    data = post_data(report, scam_type="other")
    Report.objects.filter(pk=report.pk).update(last_activity_at=timezone.now() + timedelta(1))

    resp = post(save_url(report), data)

    assert resp.status_code == 409
    assert "changed" in resp.content.decode()
    report.refresh_from_db()
    assert report.scam_type == "momo_fraud"


def test_token_changes_when_a_subject_is_confirmed_elsewhere(make_report, post):
    report = make_report()
    data = post_data(report)
    ReportSubject.objects.filter(report=report).update(confirmed=True)

    assert post(save_url(report), data).status_code == 409


@pytest.mark.parametrize("name", ["\u0301", "\u0301\u0302", "   "])
def test_payee_name_without_letters_is_refused_not_a_500(make_report, post, name):
    report = make_report()

    resp = post(save_url(report), post_data(report, add_name=name))

    assert resp.status_code == 302
    assert report.subjects.count() == 1
    assert not AuditLog.objects.filter(action="report.edit").exists()


def test_payee_name_longer_than_the_column_after_normalisation_is_refused(make_report, post):
    report = make_report()
    # NFKD expands each ligature to three characters, so 100 of them normalise to 300.
    resp = post(save_url(report), post_data(report, add_name="\ufb03" * 100))

    assert resp.status_code == 302
    assert report.subjects.count() == 1


@pytest.mark.parametrize("bad", ["1999-12-31", "0001-01-01"])
def test_incident_date_before_2000_is_refused(make_report, post, bad):
    report = make_report()
    before = Report.objects.filter(pk=report.pk).values().get()

    post(save_url(report), post_data(report, incident_date=bad))

    assert Report.objects.filter(pk=report.pk).values().get() == before


def test_adding_a_phone_already_present_as_unconfirmed_payee_confirms_it_as_seller(
    make_report, post
):
    report = make_report(status="approved")
    subject = report.subjects.get()
    subject.role = "payee"
    subject.save()
    assert warm().band == "green"  # approved but unconfirmed does not count

    post(save_url(report), post_data(report, add_phone="677123456"))

    assert report.subjects.count() == 1
    subject.refresh_from_db()
    assert (subject.role, subject.confirmed) == ("seller", True)
    assert band_for_phone(SELLER).band == "orange"
