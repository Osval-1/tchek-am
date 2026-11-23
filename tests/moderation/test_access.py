import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

pytestmark = pytest.mark.django_db

# (url name, takes report id, takes evidence id, method)
VIEWS = [
    ("moderation:queue", None, "get"),
    ("moderation:review", "report", "get"),
    ("moderation:save", "report", "post"),
    ("moderation:decide", "report", "post"),
    ("moderation:reveal", "report", "post"),
    ("moderation:evidence", "evidence", "get"),
]


@pytest.fixture
def urls(make_report):
    report = make_report()
    args = {"report": [report.pk], "evidence": [report.evidence.first().pk], None: []}
    return [(reverse(name, args=args[kind]), method) for name, kind, method in VIEWS]


def test_anonymous_is_redirected_to_admin_login(client, urls):
    for url, method in urls:
        resp = getattr(client, method)(url)
        assert resp.status_code == 302, url
        assert resp["Location"].startswith(reverse("admin:login")), url


def test_non_staff_gets_403(plain_client, urls):
    for url, method in urls:
        assert getattr(plain_client, method)(url).status_code == 403, url


def test_staff_is_let_in(staff_client, urls):
    for url, method in urls:
        status = getattr(staff_client, method)(url).status_code
        assert status in (200, 302, 303, 409), (url, status)  # POSTs fail validation, not access


def test_inactive_staff_is_redirected(client, staff, urls):
    client.force_login(staff)
    staff.is_active = False
    staff.save()
    for url, method in urls:
        assert getattr(client, method)(url).status_code == 302


def test_post_only_views_reject_get_and_get_views_reject_post(staff_client, urls):
    for url, method in urls:
        other = "get" if method == "post" else "post"
        assert getattr(staff_client, other)(url).status_code == 405, url


def test_csrf_is_enforced_on_every_post(make_report, staff, otp_login):
    from django.test import Client

    report = make_report()
    client = Client(enforce_csrf_checks=True)
    otp_login(client, staff)
    for name in ("save", "decide", "reveal"):
        resp = client.post(reverse(f"moderation:{name}", args=[report.pk]), {"action": "approve"})
        assert resp.status_code == 403, name
    report.refresh_from_db()
    assert report.status == "pending"


def test_get_views_do_not_change_state(staff_client, make_report):
    from tchekam.core.models import AuditLog
    from tchekam.reports.models import ModerationDecision, Report

    report = make_report()
    before = Report.objects.filter(pk=report.pk).values().get()
    staff_client.get(reverse("moderation:queue"))
    staff_client.get(reverse("moderation:review", args=[report.pk]))
    assert Report.objects.filter(pk=report.pk).values().get() == before
    assert not ModerationDecision.objects.exists()
    assert not AuditLog.objects.exists()


@pytest.mark.parametrize("status", ["draft", "withdrawn"])
def test_unconsented_reports_are_not_viewable(staff_client, make_report, status):
    report = make_report(status=status)
    ev = report.evidence.first()
    assert staff_client.get(reverse("moderation:review", args=[report.pk])).status_code == 404
    assert staff_client.get(reverse("moderation:evidence", args=[ev.pk])).status_code == 404
    for name in ("save", "decide", "reveal"):
        resp = staff_client.post(
            reverse(f"moderation:{name}", args=[report.pk]), {"action": "approve"}
        )
        assert resp.status_code == 404, name
    # no flash message leaks that the report exists
    assert not list(get_messages(staff_client.get(reverse("moderation:queue")).wsgi_request))
