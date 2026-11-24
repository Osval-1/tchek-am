"""Legal-hold toggles in the moderation admin: reports, numbers, users; every change audited."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tchekam.conversations.models import BotUser
from tchekam.core.models import AuditLog
from tchekam.identifiers.models import PhoneNumber
from tchekam.reports.models import Report

from .builders import phone, report, user

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client, otp_login):
    admin = get_user_model().objects.create_superuser("root", password="x")
    otp_login(client, admin)
    return admin


def _toggle(client, model, obj, action):
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
    return client.post(url, {"action": action, "_selected_action": [obj.pk]})


@pytest.mark.parametrize(
    ("model", "make"),
    [(Report, lambda: report("approved")), (PhoneNumber, phone), (BotUser, user)],
)
def test_place_and_release_legal_hold(client, staff, model, make):
    obj = make()

    assert _toggle(client, model, obj, "place_legal_hold").status_code == 302
    assert model.objects.get(pk=obj.pk).legal_hold is True
    placed = AuditLog.objects.get(action="retention.legal_hold.placed")
    assert placed.actor == staff and placed.object_id == str(obj.pk)
    assert placed.object_type == model._meta.label_lower

    _toggle(client, model, obj, "release_legal_hold")
    assert model.objects.get(pk=obj.pk).legal_hold is False
    assert AuditLog.objects.filter(action="retention.legal_hold.released").count() == 1


def test_toggling_to_the_same_state_is_not_audited_twice(client, staff):
    obj = phone()
    _toggle(client, PhoneNumber, obj, "place_legal_hold")
    _toggle(client, PhoneNumber, obj, "place_legal_hold")

    assert AuditLog.objects.filter(action="retention.legal_hold.placed").count() == 1


def test_user_admin_never_shows_the_phone_number(client, staff):
    u = user()
    url = reverse("admin:conversations_botuser_changelist")

    page = client.get(url).content.decode()
    detail = client.get(reverse("admin:conversations_botuser_change", args=[u.pk]))

    assert u.wa_phone not in page
    assert u.wa_phone not in detail.content.decode()


def test_user_admin_finds_a_user_by_exact_number(client, staff):
    u = user()
    url = reverse("admin:conversations_botuser_changelist")

    page = client.get(url, {"q": u.wa_phone}).content.decode()

    assert f"BotUser#{u.pk}" in page


@pytest.mark.parametrize(
    ("model", "make"),
    [(Report, lambda: report("approved")), (PhoneNumber, phone), (BotUser, user)],
)
def test_view_only_staff_cannot_see_or_use_the_hold_actions(client, otp_login, model, make):
    from django.contrib.auth.models import Permission

    viewer = get_user_model().objects.create_user("viewer", password="x", is_staff=True)
    viewer.user_permissions.add(Permission.objects.get(codename=f"view_{model._meta.model_name}"))
    otp_login(client, viewer)
    obj = make()
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")

    page = client.get(url).content.decode()
    _toggle(client, model, obj, "place_legal_hold")

    assert "place_legal_hold" not in page
    assert model.objects.get(pk=obj.pk).legal_hold is False
    assert not AuditLog.objects.filter(action__startswith="retention.legal_hold").exists()


def test_staff_with_the_hold_permission_can_toggle(client, otp_login):
    from django.contrib.auth.models import Permission

    officer = get_user_model().objects.create_user("officer", password="x", is_staff=True)
    officer.user_permissions.add(
        Permission.objects.get(codename="view_phonenumber"),
        Permission.objects.get(codename="manage_legal_hold"),
    )
    otp_login(client, officer)
    obj = phone()

    _toggle(client, PhoneNumber, obj, "place_legal_hold")

    assert PhoneNumber.objects.get(pk=obj.pk).legal_hold is True
