import importlib

import pytest


@pytest.fixture
def prod(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 60)
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    from tchekam.settings import prod

    yield importlib.reload(prod)


def test_prod_security_settings(prod):
    assert prod.DEBUG is False
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SECURE_HSTS_SECONDS > 0
    assert prod.ALLOWED_HOSTS == ["example.com"]


def test_prod_requires_allowed_hosts(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 60)
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    from django.core.exceptions import ImproperlyConfigured

    from tchekam.settings import prod

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(prod)
