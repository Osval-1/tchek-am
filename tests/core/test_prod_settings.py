import importlib

import pytest


def _set_required_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 60)
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@db:5432/x")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://s3.example.com")
    monkeypatch.setenv("S3_BUCKET", "b")
    monkeypatch.setenv("S3_ACCESS_KEY", "ak")
    monkeypatch.setenv("S3_SECRET_KEY", "sk")
    monkeypatch.setenv("WASENDER_WEBHOOK_SECRET", "whsec")
    monkeypatch.setenv("WASENDER_API_KEY", "wk")
    monkeypatch.setenv("TERMS_URL", "https://example.com/terms")
    monkeypatch.setenv("REPORTER_KEY_SECRET", "rk" * 32)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")
    monkeypatch.setenv("GROQ_API_KEY", "gk-test")


@pytest.fixture
def prod(monkeypatch):
    _set_required_env(monkeypatch)
    from tchekam.settings import prod

    yield importlib.reload(prod)


def test_prod_security_settings(prod):
    assert prod.DEBUG is False
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SECURE_HSTS_SECONDS > 0
    assert prod.ALLOWED_HOSTS == ["example.com"]
    assert prod.REPORTER_KEY_SECRET == "rk" * 32


def test_prod_session_and_cookie_hardening(prod):
    assert prod.SESSION_COOKIE_SECURE is True and prod.CSRF_COOKIE_SECURE is True
    assert prod.SECURE_HSTS_SECONDS > 0
    assert prod.SESSION_COOKIE_HTTPONLY is True
    assert prod.SESSION_COOKIE_SAMESITE == "Strict"
    assert prod.CSRF_COOKIE_SAMESITE == "Strict"
    assert prod.SESSION_COOKIE_AGE == 8 * 3600
    assert prod.SESSION_SAVE_EVERY_REQUEST is True  # idle, not absolute, timeout
    assert prod.SESSION_EXPIRE_AT_BROWSER_CLOSE is True


def test_prod_enforces_otp(prod):
    auth = prod.MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware")
    assert prod.MIDDLEWARE[auth + 1] == "django_otp.middleware.OTPMiddleware"
    assert "tchekam.core.apps.TchekAdminConfig" in prod.INSTALLED_APPS
    assert "django.contrib.admin" not in prod.INSTALLED_APPS
    assert prod.OTP_TOTP_ISSUER == "Tchek-Am" and prod.OTP_TOTP_THROTTLE_FACTOR == 5


def test_prod_uses_the_shared_database_cache(prod):
    # Web (moderation) and worker (checks) must see the same band invalidations.
    assert prod.CACHES["default"]["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"


def test_prod_requires_allowed_hosts(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    from django.core.exceptions import ImproperlyConfigured

    from tchekam.settings import prod

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(prod)


@pytest.mark.parametrize(
    "name",
    [
        "S3_SECRET_KEY",
        "S3_ENDPOINT_URL",
        "DATABASE_URL",
        "WASENDER_WEBHOOK_SECRET",
        "WASENDER_API_KEY",
        "TERMS_URL",
        "REPORTER_KEY_SECRET",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
    ],
)
def test_prod_requires_infra_settings(monkeypatch, name):
    _set_required_env(monkeypatch)
    monkeypatch.delenv(name)
    from django.core.exceptions import ImproperlyConfigured

    from tchekam.settings import prod

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(prod)
