import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tchekam.core.audit import audit
from tchekam.core.models import AuditLog

pytestmark = pytest.mark.django_db


def test_audit_helper_records_row():
    user = get_user_model().objects.create_user("a", password="x")

    row = audit(user, "report.approve", user, ip="10.0.0.1", note="ok")

    row.refresh_from_db()
    assert (row.actor, row.action, row.object_type, row.object_id) == (
        user,
        "report.approve",
        "auth.user",
        str(user.pk),
    )
    assert row.metadata == {"note": "ok"}
    assert row.ip == "10.0.0.1"


def test_audit_without_actor_or_object():
    row = audit(None, "system.boot")

    assert row.actor is None
    assert row.object_type == "" and row.object_id == ""


def test_update_existing_row_raises():
    row = audit(None, "a")
    row.action = "b"

    with pytest.raises(RuntimeError):
        row.save()


def test_delete_raises():
    row = audit(None, "a")

    with pytest.raises(RuntimeError):
        row.delete()


def test_queryset_update_and_delete_raise():
    audit(None, "a")

    with pytest.raises(RuntimeError):
        AuditLog.objects.update(action="b")
    with pytest.raises(RuntimeError):
        AuditLog.objects.all().delete()
    assert AuditLog.objects.count() == 1


def test_admin_is_read_only(client, otp_login):
    admin = get_user_model().objects.create_superuser("root", password="x")
    row = audit(None, "a")
    otp_login(client, admin)

    assert client.get(reverse("admin:core_auditlog_changelist")).status_code == 200
    assert client.get(reverse("admin:core_auditlog_add")).status_code == 403
    assert client.post(reverse("admin:core_auditlog_delete", args=[row.pk])).status_code == 403
    change = client.get(reverse("admin:core_auditlog_change", args=[row.pk]))
    assert change.status_code == 200
    assert b'name="action"' not in change.content
