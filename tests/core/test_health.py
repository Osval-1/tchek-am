from unittest import mock

import pytest


@pytest.mark.django_db
def test_healthz_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_healthz_returns_503_when_db_fails(client):
    # Patch the backend class: `connection` is a thread-local proxy without a patchable `cursor`.
    with mock.patch(
        "django.db.backends.base.base.BaseDatabaseWrapper.cursor",
        side_effect=Exception("db down"),
    ):
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "error"}
