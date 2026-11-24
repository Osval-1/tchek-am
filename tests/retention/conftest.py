import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clean(object_store):
    # Bands are cached per number; LocMem would leak them between tests.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    """Call a rule at the fixed NOW and run its after-commit work (blob deletion, cache)."""
    from .builders import NOW

    def call(rule, now=NOW, **kw):
        with django_capture_on_commit_callbacks(execute=True):
            return rule(now, **kw)

    return call
