import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse

from tchekam.checks.models import CheckLog
from tchekam.conversations.models import BotUser
from tchekam.imaging.models import Image
from tchekam.reports.models import Evidence, ModerationDecision, Report, ReportLink, ReportSubject

pytestmark = pytest.mark.django_db

MODELS = [Image, Report, Evidence, ReportSubject, ReportLink, ModerationDecision, CheckLog]


@pytest.fixture
def client_su(client, otp_login):
    otp_login(client, get_user_model().objects.create_superuser("root", password="x"))
    return client


@pytest.mark.parametrize("model", MODELS)
def test_changelist_loads(client_su, model):
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
    assert client_su.get(url).status_code == 200


LOCKED_REPORT_FIELDS = {
    "status", "merged_into", "submitted_at", "decided_at", "incident_date", "reference",
    "reporter", "created_at", "last_activity_at", "legal_hold", "has_payment_proof",
    "evidence_score",
}  # fmt: skip


def test_report_workflow_fields_are_readonly():
    assert LOCKED_REPORT_FIELDS <= set(admin.site._registry[Report].readonly_fields)


@pytest.mark.parametrize("model", [Report, Evidence, ModerationDecision])
def test_no_delete_permission(model):
    assert not admin.site._registry[model].has_delete_permission(None)


def test_moderation_decision_admin_is_read_only():
    ma = admin.site._registry[ModerationDecision]
    assert not ma.has_add_permission(None)
    assert not ma.has_change_permission(None)


def test_fk_admins_use_raw_id_fields():
    assert {"reporter", "merged_into"} <= set(admin.site._registry[Report].raw_id_fields)
    assert {"report_a", "report_b"} <= set(admin.site._registry[ReportLink].raw_id_fields)
    assert {"phone_number", "account_name", "image", "report"} <= set(
        admin.site._registry[ReportSubject].raw_id_fields
    )
    assert "user" in admin.site._registry[CheckLog].raw_id_fields
    assert "moderator" in admin.site._registry[ModerationDecision].raw_id_fields


def test_evidence_admin_hides_object_key_and_is_readonly(client_su):
    ma = admin.site._registry[Evidence]
    assert "object_key" not in ma.list_display
    assert "object_key" in ma.exclude
    assert not ma.has_add_permission(None)
    assert not ma.has_change_permission(None)

    user = BotUser.objects.create(wa_phone="+237600000001")
    ev = Evidence.objects.create(
        report=Report.objects.create(reporter=user),
        object_key="secret/key",
        mimetype="image/png",
        sha256="b" * 64,
        size_bytes=1,
    )
    resp = client_su.get(reverse("admin:reports_evidence_change", args=[ev.pk]))
    assert resp.status_code == 200
    assert b"secret/key" not in resp.content
