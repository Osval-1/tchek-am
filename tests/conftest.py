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


@pytest.fixture
def fake_web():
    """The FakeWebImageSearch singleton behind get_web_search() when WEB_SEARCH_BACKEND="fake"."""
    from tchekam.imaging.web import FakeWebImageSearch

    web = FakeWebImageSearch.instance()
    web.reset()
    yield web
    web.reset()


@pytest.fixture
def object_store():
    """The shared InMemoryObjectStore that get_object_store() returns under the "memory" backend."""
    from tchekam.core.storage import InMemoryObjectStore

    store = InMemoryObjectStore.instance()
    store.reset()
    yield store
    store.reset()


@pytest.fixture
def otp_login():
    """Log `user` in with a verified OTP session (what a real password + token login yields)."""
    from django_otp import DEVICE_ID_SESSION_KEY
    from django_otp.plugins.otp_totp.models import TOTPDevice

    def login(client, user):
        device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
        client.force_login(user)
        session = client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        return device

    return login


@pytest.fixture
def make_partner_group(db):
    """Create a consented PartnerGroup (status active unless overridden)."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from tchekam.groups.models import PartnerGroup

    counter = iter(range(1, 10_000))

    def make(group_jid=None, **kwargs):
        n = next(counter)
        recorder = kwargs.pop("consent_recorded_by", None) or get_user_model().objects.create_user(
            f"group-staff-{n}", is_staff=True
        )
        now = timezone.now()
        defaults = {
            "name": f"Market {n}",
            "admin_phone": "+237690000001",
            "consent_at": now,
            "notice_confirmed_at": now,
        }
        return PartnerGroup.objects.create(
            group_jid=group_jid or f"12036300000000{n:04d}@g.us",
            consent_recorded_by=recorder,
            **{**defaults, **kwargs},
        )

    return make
