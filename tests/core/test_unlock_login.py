import io

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError

from tchekam.core import login_throttle
from tchekam.core.models import AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()


def run(*args):
    out = io.StringIO()
    call_command("unlock_login", *args, stdout=out)
    return out.getvalue()


def test_unlocks_a_username_and_audits_only_the_hash():
    for _ in range(5):
        login_throttle.record_failure("Mod", None)
    assert login_throttle.is_locked("mod", None)

    out = run("mod")

    assert not login_throttle.is_locked("mod", None)
    row = AuditLog.objects.get(action="moderator.login_unlocked")
    assert row.actor is None
    assert set(row.metadata) == {"kind", "hash"} and row.metadata["kind"] == "username"
    assert len(row.metadata["hash"]) == 8 and "mod" not in str(row.metadata)
    assert row.metadata["hash"] in out


def test_unlocks_an_ip():
    for _ in range(20):
        login_throttle.record_failure("x", "203.0.113.9")
    assert login_throttle.is_locked("other", "203.0.113.9")

    run("--ip", "203.0.113.9")

    assert not login_throttle.is_locked("other", "203.0.113.9")
    row = AuditLog.objects.get(action="moderator.login_unlocked")
    assert row.metadata["kind"] == "ip" and "203" not in str(row.metadata)


def test_needs_exactly_one_target_and_a_valid_ip():
    for args in ((), ("mod", "--ip", "1.2.3.4"), ("--ip", "nope")):
        with pytest.raises(CommandError):
            run(*args)
    assert not AuditLog.objects.exists()
