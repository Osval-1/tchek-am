import pytest
from django.core.cache import cache

from tchekam.reputation import appeals_hook


@pytest.fixture(autouse=True)
def _isolate():
    # Bands are cached per number for an hour; LocMem would leak them between tests.
    cache.clear()
    appeals_hook.set_provider(None)
    yield
    cache.clear()
    appeals_hook.set_provider(None)
