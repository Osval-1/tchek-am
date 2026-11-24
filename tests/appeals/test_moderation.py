"""Moderator appeal pages: access control, evidence audit, decisions."""

from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from tchekam.appeals.models import Appeal, AppealEvidence
from tchekam.core.audit import AuditLog
from tchekam.identifiers.models import get_or_create_phone
from tchekam.reputation.facts import Band
from tchekam.reputation.service import band_for_phone

from .conftest import OWN, months_ago

pytestmark = pytest.mark.django_db


@pytest.fixture
def appeal(bot, object_store):
    a = Appeal.objects.create(
        phone_number=get_or_create_phone(OWN),
        appellant=bot.user,
        kind="wrong",
        statement="Please look again",
        status="open",
        submitted_at=timezone.now(),
    )
    object_store.put("appeal-evidence/k1", b"x", "image/png")
    AppealEvidence.objects.create(
        appeal=a, object_key="appeal-evidence/k1", mimetype="image/png",
        sha256="a" * 64, size_bytes=1, source_message_id="m1",
    )  # fmt: skip
    return a


@pytest.fixture
def client_for(staff, otp_login):
    def make(user=None):
        c = Client()
        otp_login(c, user or staff)
        return c

    return make


def urls(appeal):
    ev = appeal.evidence.first()
    return [
        reverse("moderation:appeal_queue"),
        reverse("moderation:appeal_review", args=[appeal.pk]),
        reverse("moderation:appeal_evidence", args=[ev.pk]),
    ]


def test_anonymous_and_password_only_sessions_are_sent_to_login(appeal, staff):
    anonymous = Client()
    password_only = Client()
    password_only.force_login(staff)  # no OTP device verified
    for client in (anonymous, password_only):
        for url in urls(appeal):
            assert client.get(url).status_code == 302
        post = client.post(
            reverse("moderation:appeal_decide", args=[appeal.pk]), {"action": "reject"}
        )
        assert post.status_code == 302
    appeal.refresh_from_db()
    assert appeal.status == "open"
    assert not AuditLog.objects.filter(action="appeal_evidence.view").exists()


def test_verified_non_staff_gets_403(appeal, client_for, django_user_model):
    plain = django_user_model.objects.create_user("plain", password="x")
    client = client_for(plain)
    assert all(client.get(url).status_code == 403 for url in urls(appeal))


def test_queue_and_review_show_what_a_moderator_needs_and_nothing_more(
    appeal, client_for, make_report, bot
):
    report = make_report(incident=months_ago(4))
    client = client_for()
    queue = client.get(reverse("moderation:appeal_queue"))
    assert OWN in queue.content.decode() and queue["Cache-Control"] == "no-store"
    page = client.get(reverse("moderation:appeal_review", args=[appeal.pk]))
    html = page.content.decode()
    assert "Please look again" in html and report.reference in html
    assert page["Referrer-Policy"] == "no-referrer"
    # No reporter identity, no appellant account details.
    assert report.reporter.wa_phone not in html
    assert f"BotUser#{bot.user.pk}" not in html


def test_evidence_only_via_audited_signed_url(appeal, client_for, staff):
    ev = appeal.evidence.get()
    client = client_for()
    for _ in range(2):
        response = client.get(reverse("moderation:appeal_evidence", args=[ev.pk]))
        assert response.status_code == 302 and response["Location"].startswith("memory://")
    assert (
        AuditLog.objects.filter(
            action="appeal_evidence.view", actor=staff, object_id=str(ev.pk)
        ).count()
        == 2
    )
    assert ev.object_key not in client.get(urls(appeal)[1]).content.decode().replace(
        f"/appeal-evidence/{ev.pk}/", ""
    )


def test_drafts_are_invisible_to_staff(appeal, client_for):
    Appeal.objects.filter(pk=appeal.pk).update(status="draft")
    client = client_for()
    assert client.get(urls(appeal)[1]).status_code == 404
    assert client.get(urls(appeal)[2]).status_code == 404
    assert client.post(reverse("moderation:appeal_decide", args=[appeal.pk])).status_code == 404


def test_missing_evidence_blob_is_404(appeal, client_for, object_store):
    object_store.reset()
    assert client_for().get(urls(appeal)[2]).status_code == 404


def test_decide_via_form_approves_selected_reports(
    appeal, client_for, make_report, django_capture_on_commit_callbacks
):
    drop = make_report(incident=months_ago(4))
    client = client_for()
    assert band_for_phone(OWN).band == Band.RED
    url = reverse("moderation:appeal_decide", args=[appeal.pk])
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(url, {"action": "approve", "report": [str(drop.pk)]})
    assert response.status_code == 302
    appeal.refresh_from_db()
    drop.refresh_from_db()
    assert (appeal.status, drop.status) == ("approved", "rejected")
    assert band_for_phone(OWN).band == Band.GREEN
    again = client.post(url, {"action": "reject", "reason": "x"}, follow=True)
    assert "already been decided" in again.content.decode()


def test_decide_errors_are_shown_and_change_nothing(appeal, client_for):
    client = client_for()
    url = reverse("moderation:appeal_decide", args=[appeal.pk])
    page = client.post(url, {"action": "approve"}, follow=True).content.decode()
    assert "Select at least one report" in page
    page = client.post(url, {"action": "reject"}, follow=True).content.decode()
    assert "reason is required" in page
    appeal.refresh_from_db()
    assert appeal.status == "open"


def test_review_of_decided_appeal_has_no_form(appeal, client_for, staff):
    Appeal.objects.filter(pk=appeal.pk).update(status="rejected", decided_at=timezone.now())
    html = client_for().get(urls(appeal)[1]).content.decode()
    assert "<form" not in html


def test_reputation_never_imports_appeals():
    root = Path(__file__).resolve().parents[2] / "src" / "tchekam" / "reputation"
    for path in root.glob("*.py"):
        assert "tchekam.appeals" not in path.read_text(encoding="utf-8"), path
