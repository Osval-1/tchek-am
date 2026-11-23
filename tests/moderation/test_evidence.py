import pytest
from django.urls import reverse

from tchekam.core.models import AuditLog

pytestmark = pytest.mark.django_db


def url_for(report):
    return reverse("moderation:evidence", args=[report.evidence.first().pk])


def test_redirects_to_a_five_minute_signed_url_with_private_headers(staff_client, make_report):
    report = make_report()
    ev = report.evidence.first()

    resp = staff_client.get(url_for(report))

    assert resp.status_code == 302
    assert resp["Location"] == f"memory://{ev.object_key}?ttl=300"
    assert resp["Cache-Control"] == "no-store"
    assert resp["Referrer-Policy"] == "no-referrer"


def test_every_request_writes_one_audit_entry(staff_client, make_report):
    report = make_report()
    for _ in range(3):
        staff_client.get(url_for(report), REMOTE_ADDR="10.1.2.3")

    entries = AuditLog.objects.filter(action="evidence.view")
    assert entries.count() == 3
    entry = entries.first()
    assert entry.object_type == "reports.evidence" and entry.actor.username == "mod"
    assert entry.ip == "10.1.2.3"
    assert "evidence/secret" not in str(entry.metadata)


def test_forwarded_for_is_ignored_unless_proxy_is_trusted(staff_client, make_report, settings):
    report = make_report()
    headers = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "203.0.113.9, 10.0.0.1"}

    staff_client.get(url_for(report), **headers)
    settings.TRUST_PROXY_HEADERS = True
    staff_client.get(url_for(report), **headers)
    staff_client.get(url_for(report), REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="not-an-ip")

    ips = list(AuditLog.objects.order_by("id").values_list("ip", flat=True))
    assert ips == ["10.0.0.1", "203.0.113.9", None]


def test_missing_blob_is_404_and_unknown_evidence_is_404(staff_client, make_report, object_store):
    report = make_report()
    object_store.delete(report.evidence.first().object_key)

    assert staff_client.get(url_for(report)).status_code == 404
    assert staff_client.get(reverse("moderation:evidence", args=[999999])).status_code == 404
