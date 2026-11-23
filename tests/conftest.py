# Shared fixtures live here; DB access is opted into per test via pytest-django marks.
import pytest


@pytest.fixture
def fake_channel():
    """The FakeChannel singleton that get_channel() returns under MESSAGING_CHANNEL="fake"."""
    from tchekam.messaging.fake import FakeChannel

    channel = FakeChannel.instance()
    channel.reset()
    yield channel
    channel.reset()
