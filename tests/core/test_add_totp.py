import io

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from tchekam.core.models import AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff():
    return get_user_model().objects.create_user("mod", password="x", is_staff=True)


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    call_command("add_totp", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_enrols_a_confirmed_device_and_prints_everything_once(staff):
    out, err = run("mod")

    assert TOTPDevice.objects.get(user=staff).confirmed
    assert "Secret (base32):" in out and "otpauth://totp/Tchek-Am%3Amod" in out
    assert any(ch in out for ch in "█▀▄")  # the ASCII QR
    tokens = [t.token for t in StaticDevice.objects.get(user=staff).token_set.all()]
    assert len(tokens) == 8 and all(t in out for t in tokens)
    assert err == ""


def test_refuses_non_staff_inactive_and_unknown_users():
    get_user_model().objects.create_user("plain", password="x")
    get_user_model().objects.create_user("gone", password="x", is_staff=True, is_active=False)
    for name in ("plain", "gone", "nobody"):
        with pytest.raises(CommandError):
            run(name)
    assert not TOTPDevice.objects.exists()


def test_refuses_an_existing_device_unless_replace(staff):
    run("mod")
    first = TOTPDevice.objects.get(user=staff).key

    with pytest.raises(CommandError):
        run("mod")
    assert TOTPDevice.objects.get(user=staff).key == first

    run("mod", "--replace")
    assert TOTPDevice.objects.get(user=staff).key != first
    assert StaticDevice.objects.filter(user=staff).count() == 1


def test_writes_an_audit_row_without_secrets(staff):
    run("mod")

    row = AuditLog.objects.get(action="moderator.totp_enrolled")
    assert row.actor is None and row.object_id == str(staff.pk)
    assert row.object_type == "auth.user"
    assert TOTPDevice.objects.get(user=staff).key not in str(row.metadata)


def test_qr_that_the_terminal_cannot_encode_does_not_hide_the_tokens(staff):
    class Cp1252(io.StringIO):
        encoding = "cp1252"

    out = Cp1252()
    call_command("add_totp", "mod", stdout=out)

    text = out.getvalue()
    tokens = [t.token for t in StaticDevice.objects.get(user=staff).token_set.all()]
    assert "QR not shown" in text and all(t in text for t in tokens)
