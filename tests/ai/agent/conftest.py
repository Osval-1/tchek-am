import pytest

from tchekam.ai.models import AgentControl, AgentRun
from tchekam.conversations.models import BotUser, Conversation
from tchekam.messaging.models import InboundEvent


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    import socket

    original = socket.socket.connect

    def connect(sock, address):
        # Local test PostgreSQL is permitted; inference, telemetry and media are not.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
            return original(sock, address)
        raise AssertionError("External network forbidden in agent tests")

    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture
def agent_settings(settings):
    settings.AGENT_ENABLED = True
    settings.AGENT_MEMORY_KEYS = {"v1": "test-memory-key"}
    settings.AGENT_OPERATION_KEY = "test-operation-key"
    settings.AGENT_DAILY_BUDGET_MICROUSD = 100
    settings.AGENT_MONTHLY_BUDGET_MICROUSD = 1000
    return settings


@pytest.fixture
def actor(agent_settings, db):
    user = BotUser.objects.create(wa_phone="+237690000001", language="en")
    Conversation.objects.create(user=user)
    control = AgentControl.objects.create(pk=1, enabled=True, rollout_percentage=100)
    control.pilot_users.add(user)
    return user


@pytest.fixture
def make_run(actor):
    def make(text="Is this number OK?", kind="text", user=None):
        user = user or actor
        conv = Conversation.objects.get(user=user)
        conv.agent_sequence += 1
        conv.save()
        key = f"msg-{user.pk}-{conv.agent_sequence}"
        descriptor = (
            {"conversation": text} if kind == "text" else {f"{kind}Message": {"caption": text}}
        )
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "id": key,
                    "remoteJid": user.wa_phone.lstrip("+") + "@s.whatsapp.net",
                    "fromMe": False,
                },
                "message": descriptor,
            },
        }
        event = InboundEvent.objects.create(
            message_id=key, event="messages.upsert", payload=payload
        )
        return AgentRun.objects.create(
            user=user,
            inbound=event,
            inbound_key=key,
            generation=conv.agent_generation,
            sequence=conv.agent_sequence,
        )

    return make
