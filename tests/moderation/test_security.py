from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from tchekam.core.models import AuditLog

from .test_access import VIEWS

pytestmark = pytest.mark.django_db


@pytest.fixture
def urls(make_report):
    report = make_report()
    args = {"report": [report.pk], "evidence": [report.evidence.first().pk], None: []}
    return [(reverse(name, args=args[kind]), method) for name, kind, method in VIEWS]


@pytest.fixture
def password_only_client(client, staff):
    client.force_login(staff)  # logged in, but never passed the OTP step
    return client


def current_token(device):
    return f"{totp(device.bin_key, device.step, device.t0, device.digits, device.drift):06d}"


def login_form(client, user, token, device, password="x"):
    return client.post(
        reverse("admin:login"),
        {
            "username": user.username,
            "password": password,
            "otp_device": device.persistent_id,
            "otp_token": token,
            "next": reverse("moderation:queue"),
        },
    )


def test_staff_without_otp_is_redirected_on_every_moderation_route(password_only_client, urls):
    for url, method in urls:
        resp = getattr(password_only_client, method)(url)
        assert resp.status_code == 302, url
        assert resp["Location"].startswith(reverse("admin:login") + "?next="), url


def test_staff_without_otp_cannot_open_admin_pages(password_only_client):
    for name in ("admin:index", "admin:core_auditlog_changelist"):
        resp = password_only_client.get(reverse(name))
        assert resp.status_code == 302
        assert resp["Location"].startswith(reverse("admin:login"))


def test_evidence_denied_without_otp_leaves_no_trace(password_only_client, make_report):
    report = make_report()
    url = reverse("moderation:evidence", args=[report.evidence.first().pk])

    resp = password_only_client.get(url)

    assert resp.status_code == 302
    assert resp["Location"].startswith(reverse("admin:login"))  # never the signed blob URL
    assert not AuditLog.objects.filter(action="evidence.view").exists()


def test_verified_non_staff_gets_403_everywhere(plain_client, urls):
    for url, method in urls:
        assert getattr(plain_client, method)(url).status_code == 403, url


def test_real_login_flow_with_a_valid_token(client, staff):
    device = TOTPDevice.objects.create(user=staff, name="phone", confirmed=True)

    resp = login_form(client, staff, current_token(device), device)

    assert resp.status_code == 302 and resp["Location"] == reverse("moderation:queue")
    assert client.get(reverse("moderation:queue")).status_code == 200
    entry = AuditLog.objects.get(action="moderator.login")
    assert entry.actor == staff and entry.ip == "127.0.0.1"


def test_wrong_token_is_rejected_and_audited_without_secrets(client, staff):
    device = TOTPDevice.objects.create(user=staff, name="phone", confirmed=True)
    wrong = f"{(int(current_token(device)) + 1) % 10**6:06d}"

    resp = login_form(client, staff, wrong, device)

    assert resp.status_code == 200
    assert client.get(reverse("moderation:queue")).status_code == 302
    assert not AuditLog.objects.filter(action="moderator.login").exists()
    entry = AuditLog.objects.get(action="moderator.login_failed")
    assert entry.actor is None
    assert set(entry.metadata) == {"username_hash"} and len(entry.metadata["username_hash"]) == 8
    assert "mod" not in str(entry.metadata) and wrong not in str(entry.metadata)


def test_wrong_password_with_a_valid_token_is_rejected(client, staff):
    device = TOTPDevice.objects.create(user=staff, name="phone", confirmed=True)

    resp = login_form(client, staff, current_token(device), device, password="nope")

    assert resp.status_code == 200
    assert client.get(reverse("moderation:queue")).status_code == 302


def test_static_recovery_token_works_once(staff):
    recovery = StaticDevice.objects.create(user=staff, name="recovery", confirmed=True)
    StaticToken.objects.create(device=recovery, token="abcd2345")

    first = Client()
    assert login_form(first, staff, "abcd2345", recovery).status_code == 302
    assert first.get(reverse("moderation:queue")).status_code == 200

    second = Client()
    assert login_form(second, staff, "abcd2345", recovery).status_code == 200
    assert second.get(reverse("moderation:queue")).status_code == 302


def test_user_without_a_device_cannot_log_in(client, staff):
    resp = client.post(reverse("admin:login"), {"username": "mod", "password": "x"})

    assert resp.status_code == 200
    assert client.get(reverse("moderation:queue")).status_code == 302


def test_verified_superuser_sees_admin_changelists(client, otp_login):
    root = get_user_model().objects.create_superuser("root", password="x")
    otp_login(client, root)

    assert client.get(reverse("admin:index")).status_code == 200
    assert client.get(reverse("admin:core_auditlog_changelist")).status_code == 200


def test_no_template_in_the_project_mentions_object_key():
    root = Path(__file__).parents[2] / "src" / "tchekam"
    files = list(root.glob("**/templates/**/*.html"))
    assert files
    assert all("object_key" not in f.read_text(encoding="utf-8") for f in files)
