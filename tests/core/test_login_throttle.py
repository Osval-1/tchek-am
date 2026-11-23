from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from tchekam.core import login_throttle
from tchekam.core.models import AuditLog

pytestmark = pytest.mark.django_db

LOCKED = login_throttle.LOCKED_MESSAGE


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()


@pytest.fixture
def staff():
    return get_user_model().objects.create_user("mod", password="x", is_staff=True)


@pytest.fixture
def clock(monkeypatch):
    """Drive cache expiry: LocMem and BaseCache read time.time() from their own module."""
    now = SimpleNamespace(t=1_000_000.0)
    fake = SimpleNamespace(time=lambda: now.t)
    monkeypatch.setattr("django.core.cache.backends.locmem.time", fake)
    monkeypatch.setattr("django.core.cache.backends.base.time", fake)
    return now


def attempt(client, username="mod", password="bad", ip="10.0.0.1"):
    resp = client.post(
        reverse("admin:login"),
        {"username": username, "password": password, "otp_token": "000000"},
        REMOTE_ADDR=ip,
    )
    return resp.content.decode()


def good_login(client, device, ip="10.0.0.1"):
    key = (device.bin_key, device.step, device.t0, device.digits, device.drift)
    return client.post(
        reverse("admin:login"),
        {
            "username": "mod",
            "password": "x",
            "otp_device": device.persistent_id,
            "otp_token": f"{totp(*key):06d}",
        },
        REMOTE_ADDR=ip,
    )


def test_locks_after_five_failures_for_a_username(client, staff):
    for i in range(5):
        assert LOCKED not in attempt(client, ip=f"10.0.0.{i + 1}")
    assert LOCKED in attempt(client, ip="10.0.9.9")


def test_a_locked_username_rejects_even_the_right_credentials(client, staff):
    device = TOTPDevice.objects.create(user=staff, name="p", confirmed=True)
    for i in range(5):
        attempt(client, ip=f"10.0.0.{i + 1}")

    assert LOCKED in good_login(client, device, ip="10.0.9.9").content.decode()


def test_unknown_usernames_get_the_same_lock_message(client, staff):
    for i in range(5):
        attempt(client, username="ghost", ip=f"10.0.0.{i + 1}")
    ghost = attempt(client, username="ghost", ip="10.0.9.9")
    for i in range(5):
        attempt(client, username="mod", ip=f"10.0.1.{i + 1}")
    real = attempt(client, username="mod", ip="10.0.9.9")

    assert LOCKED in ghost and LOCKED in real


def test_username_case_cannot_dodge_the_lock(client, staff):
    for i in range(5):
        attempt(client, username="MOD" if i % 2 else "mod", ip=f"10.0.0.{i + 1}")
    assert LOCKED in attempt(client, username="Mod", ip="10.0.9.9")


def test_lock_expires_after_fifteen_minutes(client, staff, clock):
    for i in range(5):
        attempt(client, ip=f"10.0.0.{i + 1}")
    assert LOCKED in attempt(client, ip="10.0.9.9")

    clock.t += 15 * 60 + 1

    assert LOCKED not in attempt(client, ip="10.0.9.9")


def test_ip_locks_after_twenty_failures_across_usernames(client, staff):
    for i in range(20):
        attempt(client, username=f"user{i}")
    assert LOCKED in attempt(client, username="someone-else")
    assert LOCKED not in attempt(client, username="someone-else", ip="10.0.5.5")


def test_ip_failures_below_the_threshold_do_not_block_a_valid_login(client, staff):
    device = TOTPDevice.objects.create(user=staff, name="p", confirmed=True)
    for i in range(19):
        attempt(client, username=f"user{i}")

    assert good_login(client, device).status_code == 302


def test_success_resets_the_username_counter(client, staff):
    device = TOTPDevice.objects.create(user=staff, name="p", confirmed=True)
    for i in range(4):
        attempt(client, ip=f"10.0.0.{i + 1}")
    assert good_login(client, device, ip="10.0.8.8").status_code == 302

    client.logout()
    for i in range(4):
        assert LOCKED not in attempt(client, ip=f"10.0.2.{i + 1}")


def test_forwarded_for_only_counts_when_the_proxy_is_trusted(client, settings):
    def hit():
        client.post(
            reverse("admin:login"),
            {"username": "u", "password": "p"},
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.9",
        )

    hit()
    assert cache.get("login_throttle:ip:10.0.0.1") == 1
    assert cache.get("login_throttle:ip:203.0.113.9") is None
    settings.TRUSTED_PROXY_COUNT = 1
    hit()
    assert cache.get("login_throttle:ip:203.0.113.9") == 1


def test_counters_never_hold_the_raw_username_or_password(client, staff):
    attempt(client, username="we!rd user", password="hunter2")

    keys = " ".join(str(k) for k in cache._cache)  # LocMem exposes its keys
    assert "hunter2" not in keys and "we!rd" not in keys and "weird" not in keys
    audit_rows = str(list(AuditLog.objects.values()))
    assert "hunter2" not in audit_rows and "we!rd" not in audit_rows


def test_unicode_spellings_of_a_username_share_one_counter(client, staff):
    variants = ["mod", "ｍｏｄ", "mｏd", "\U0001d426od", " MOD ", "m​od"]
    for i, name in enumerate(variants[:5]):
        assert LOCKED not in attempt(client, username=name, ip=f"10.0.0.{i + 1}")
    assert LOCKED in attempt(client, username=variants[5], ip="10.0.9.9")
    assert len({login_throttle.username_digest(v) for v in variants}) == 1
