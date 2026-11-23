import os
import time

import httpx
import pytest
from django.conf import settings

from tchekam.core.storage import (
    InMemoryObjectStore,
    ObjectNotFoundError,
    S3ObjectStore,
    get_object_store,
    new_key,
)


def _s3_store():
    store = S3ObjectStore.from_settings()
    try:
        httpx.get(settings.S3_ENDPOINT_URL, timeout=2)
    except httpx.HTTPError:
        # CI sets S3_REQUIRED=1 so a broken SeaweedFS start fails instead of skipping.
        if os.environ.get("S3_REQUIRED"):
            pytest.fail("S3 endpoint unreachable but S3_REQUIRED is set")
        pytest.skip("S3 endpoint unreachable")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param("s3", marks=pytest.mark.integration),
    ]
)
def store(request):
    return InMemoryObjectStore() if request.param == "memory" else _s3_store()


def test_put_returns_key_and_get_roundtrips(store):
    key = new_key()

    assert store.put(key, b"hello", "text/plain") == key
    assert store.get(key) == b"hello"


def test_get_missing_raises(store):
    with pytest.raises(ObjectNotFoundError):
        store.get(new_key())


def test_delete_removes_and_is_idempotent(store):
    key = new_key()
    store.put(key, b"x", "text/plain")

    store.delete(key)
    store.delete(key)

    with pytest.raises(ObjectNotFoundError):
        store.get(key)


def test_signed_url_is_a_string(store):
    key = new_key()
    store.put(key, b"x", "text/plain")

    assert isinstance(store.signed_url(key, 60), str)


@pytest.mark.integration
def test_s3_signed_url_serves_then_expires():
    store = _s3_store()
    key = new_key()
    store.put(key, b"secret", "text/plain")
    try:
        url = store.signed_url(key, 3)

        first = httpx.get(url)
        assert first.status_code == 200
        assert first.content == b"secret"

        time.sleep(4)
        assert httpx.get(url).status_code == 403
    finally:
        store.delete(key)


def test_new_key_is_generated_under_prefix():
    a, b = new_key(), new_key()

    assert a.startswith("evidence/") and a != b
    assert new_key("tmp").startswith("tmp/")


def test_factory_uses_memory_backend_in_tests():
    assert isinstance(get_object_store(), InMemoryObjectStore)


def test_factory_builds_s3_backend(settings):
    settings.OBJECT_STORE_BACKEND = "s3"

    assert isinstance(get_object_store(), S3ObjectStore)


def test_factory_rejects_unknown_backend(settings):
    settings.OBJECT_STORE_BACKEND = "ftp"

    with pytest.raises(ValueError):
        get_object_store()
