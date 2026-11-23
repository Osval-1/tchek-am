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


@pytest.fixture
def fake_llm():
    """The FakeLLMClient singleton that get_llm_client() returns under AI_BACKEND="fake"."""
    from tchekam.ai.fake import FakeLLMClient

    client = FakeLLMClient.instance()
    client.reset()
    yield client
    client.reset()


@pytest.fixture
def fake_speech():
    """The FakeSpeechToText singleton behind get_speech_to_text() when SPEECH_BACKEND="fake"."""
    from tchekam.speech.fake import FakeSpeechToText

    stt = FakeSpeechToText.instance()
    stt.reset()
    yield stt
    stt.reset()
