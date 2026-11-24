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
    monkeypatch.setenv("SERPAPI_API_KEY", "sk-test")
    # The dev environment has no open_clip, which prod now refuses when the backend is openclip.
    monkeypatch.setenv("EMBEDDER_BACKEND", "fake")
    from tchekam.settings import base

    importlib.reload(base)  # base reads the environment once, at import


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
        "SERPAPI_API_KEY",
    ],
)
def test_prod_requires_infra_settings(monkeypatch, name):
    _set_required_env(monkeypatch)
    monkeypatch.delenv(name)
    from django.core.exceptions import ImproperlyConfigured

    from tchekam.settings import prod

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(prod)


def test_prod_refuses_to_start_without_channel_safeguards(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CHANNEL_SAFEGUARDS", "false")
    from django.core.exceptions import ImproperlyConfigured

    from tchekam.settings import base, prod

    importlib.reload(base)  # base reads the environment once, at import
    try:
        with pytest.raises(ImproperlyConfigured):
            importlib.reload(prod)
    finally:
        monkeypatch.delenv("CHANNEL_SAFEGUARDS")
        importlib.reload(base)


def test_prod_refuses_openclip_without_the_ml_extra(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("EMBEDDER_BACKEND", "openclip")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    from django.core.exceptions import ImproperlyConfigured

    from tchekam.settings import base, prod

    importlib.reload(base)
    with pytest.raises(ImproperlyConfigured, match="WITH_ML=1"):
        importlib.reload(prod)


def test_prod_accepts_openclip_when_the_ml_extra_is_installed(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("EMBEDDER_BACKEND", "openclip")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    from tchekam.settings import base, prod

    importlib.reload(base)

    assert importlib.reload(prod).EMBEDDER_BACKEND == "openclip"


def test_prod_serves_static_files_with_whitenoise(prod):
    assert prod.MIDDLEWARE[0] == "django.middleware.security.SecurityMiddleware"
    assert prod.MIDDLEWARE[1] == "whitenoise.middleware.WhiteNoiseMiddleware"
    assert "Manifest" in prod.STORAGES["staticfiles"]["BACKEND"]
    assert str(prod.STATIC_ROOT).endswith("staticfiles")
    assert "django.contrib.staticfiles" in prod.INSTALLED_APPS  # provides collectstatic


def test_prod_does_not_init_sentry_without_a_dsn(monkeypatch):
    import sentry_sdk

    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    _set_required_env(monkeypatch)
    from tchekam.settings import prod

    importlib.reload(prod)

    assert calls == []


def test_prod_sentry_never_sends_pii_and_scrubs_events(monkeypatch):
    import sentry_sdk

    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", "https://k@o.example/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    monkeypatch.setenv("SENTRY_RELEASE", "v1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")
    from tchekam.core.observability import scrub_event
    from tchekam.settings import prod

    importlib.reload(prod)

    (kw,) = calls
    assert prod.DEBUG is False
    assert kw["send_default_pii"] is False
    assert kw["before_send"] is scrub_event
    assert (kw["environment"], kw["release"], kw["traces_sample_rate"]) == ("staging", "v1", 0.05)
