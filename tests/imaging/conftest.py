import pytest


@pytest.fixture(autouse=True)
def _store(object_store):
    return object_store
