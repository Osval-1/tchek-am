import json
from pathlib import Path

import pytest
from django.core.cache import cache

FIXTURES = Path(__file__).resolve().parents[1] / "messaging" / "fixtures"
GROUP_JID = "120363000000000001@g.us"
POSTER = "+237670000003"  # cleanedParticipantPn of the group fixtures


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clean(object_store):
    # Product verdicts are cached per sha256; LocMem would leak them between tests.
    cache.clear()
    yield
    cache.clear()
