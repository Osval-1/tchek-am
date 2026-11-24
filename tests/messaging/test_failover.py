import importlib
import io

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command

from tchekam.core.models import AuditLog
from tchekam.messaging.channel import get_channel
from tchekam.messaging.models import ChannelState

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def keys(settings):
    settings.MESSAGING_CHANNEL = "wasender"
    settings.WASENDER_API_KEY = "primary-key"
    settings.WASENDER_BACKUP_API_KEY = "backup-key"


def _key():
    return get_channel()._api.headers["Authorization"]


def switch(session):
    call_command("switch_channel", session, stdout=io.StringIO())


def test_primary_is_used_until_switched():
    assert _key() == "Bearer primary-key"


def test_switch_channel_backup_changes_the_key_used_by_get_channel():
    switch("backup")

    assert _key() == "Bearer backup-key"

    switch("primary")
    assert _key() == "Bearer primary-key"


def test_setting_is_the_default_before_any_switch(settings):
    settings.WASENDER_ACTIVE_SESSION = "backup"

    assert _key() == "Bearer backup-key"


def test_switch_writes_an_audit_row_without_secrets():
    switch("backup")

    row = AuditLog.objects.get(action="channel.switched")
    assert row.metadata == {"from": "primary", "to": "backup"}


def test_backup_is_refused_without_a_key(settings):
    settings.WASENDER_BACKUP_API_KEY = ""

    with pytest.raises(CommandError):
        switch("backup")

    assert not ChannelState.objects.exists()


def test_primary_is_refused_without_a_key(settings):
    settings.WASENDER_API_KEY = ""

    with pytest.raises(CommandError):
        switch("primary")


def test_database_is_not_read_without_a_backup_key(settings, django_assert_num_queries):
    settings.WASENDER_BACKUP_API_KEY = ""

    with django_assert_num_queries(0):
        get_channel()


def test_backup_webhook_secret_is_accepted_too(client, settings):
    settings.WASENDER_WEBHOOK_SECRET = "primary-secret"
    settings.WASENDER_BACKUP_WEBHOOK_SECRET = "backup-secret"

    def post(secret):
        return client.post(
            "/webhooks/whatsapp",
            data="{}",
            content_type="application/json",
            headers={"X-Webhook-Signature": secret},
        ).status_code

    assert post("primary-secret") == 200
    assert post("backup-secret") == 200
    assert post("other") == 401


PROD_ENV = {
    "SECRET_KEY": "k",
    "ALLOWED_HOSTS": "example.org",
    "DATABASE_URL": "postgres://u:p@localhost/db",
    "S3_ENDPOINT_URL": "http://s3",
    "S3_BUCKET": "b",
    "S3_ACCESS_KEY": "a",
    "S3_SECRET_KEY": "s",
    "WASENDER_WEBHOOK_SECRET": "w",
    "WASENDER_API_KEY": "p",
    "TERMS_URL": "https://t",
    "REPORTER_KEY_SECRET": "r",
    "ANTHROPIC_API_KEY": "a",
    "GROQ_API_KEY": "g",
    "SERPAPI_API_KEY": "s",
}


def _load_prod(monkeypatch, **extra):
    for key, value in {**PROD_ENV, **extra}.items():
        monkeypatch.setenv(key, value)
    import tchekam.settings.base as base
    import tchekam.settings.prod as prod

    importlib.reload(base)  # prod star-imports base, which reads the environment once
    return importlib.reload(prod)


def test_prod_requires_the_backup_key_when_backup_is_active(monkeypatch):
    monkeypatch.delenv("WASENDER_BACKUP_API_KEY", raising=False)
    with pytest.raises(ImproperlyConfigured):
        _load_prod(monkeypatch, WASENDER_ACTIVE_SESSION="backup")


def test_prod_rejects_an_unknown_session(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        _load_prod(monkeypatch, WASENDER_ACTIVE_SESSION="third")


def test_prod_accepts_a_configured_backup(monkeypatch):
    prod = _load_prod(monkeypatch, WASENDER_ACTIVE_SESSION="backup", WASENDER_BACKUP_API_KEY="b")

    assert prod.WASENDER_ACTIVE_SESSION == "backup"
