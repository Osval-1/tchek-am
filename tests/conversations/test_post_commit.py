"""Post-commit jobs queued by handlers, and outbound messages sent from tasks."""

import logging

import pytest

from tchekam.conversations import outbound, router
from tchekam.conversations.models import BotUser, Conversation
from tchekam.conversations.service import handle_private_message
from tchekam.core import tasks
from tchekam.messaging.channel import ChannelError, InboundMessage, RateLimited

pytestmark = pytest.mark.django_db

PHONE = "237670000077"


def msg(text, message_id="PC1"):
    return InboundMessage(
        message_id=message_id,
        sender_phone=PHONE,
        sender_jid=f"{PHONE}@s.whatsapp.net",
        chat_type="private",
        group_jid=None,
        kind="text",
        text=text,
        media=None,
        timestamp=1,
        raw_event="messages.received",
    )


@pytest.fixture
def user():
    user = BotUser.objects.create(wa_phone=f"+{PHONE}", language="en")
    Conversation.objects.create(user=user)
    return user


@pytest.fixture
def probe(monkeypatch):
    """A registered task that records what it saw of the conversation when it ran."""
    seen: list[dict] = []

    def run(**kwargs):
        conv = Conversation.objects.get(user__wa_phone=f"+{PHONE}")
        seen.append({"kwargs": kwargs, "flow": conv.flow})

    monkeypatch.setitem(tasks._REGISTRY, "test.probe", run)
    return seen


def test_jobs_run_after_the_conversation_is_saved(user, probe, monkeypatch):
    def handler(ctx):
        router.start_flow(ctx.conversation, "probe_flow")
        ctx.enqueue_after("test.probe", n=1)
        return [router.Reply("queued")]

    monkeypatch.setitem(router.INTENTS, "help", handler)

    replies = handle_private_message(msg("help"))

    assert [r.text for r in replies] == ["queued"]
    assert probe == [{"kwargs": {"n": 1}, "flow": "probe_flow"}]


def test_replies_are_delivered_before_jobs_run(user, probe, monkeypatch):
    order: list[str] = []

    def handler(ctx):
        ctx.enqueue_after("test.probe")
        return [router.Reply("hi")]

    monkeypatch.setitem(router.INTENTS, "help", handler)
    monkeypatch.setitem(tasks._REGISTRY, "test.probe", lambda **kw: order.append("job"))

    handle_private_message(msg("help"), deliver=lambda replies: order.append("deliver"))

    assert order == ["deliver", "job"]


def test_jobs_still_run_when_delivery_fails(user, probe, monkeypatch):
    def handler(ctx):
        ctx.enqueue_after("test.probe")
        return [router.Reply("hi")]

    def deliver(replies):
        raise RateLimited(5)

    monkeypatch.setitem(router.INTENTS, "help", handler)

    with pytest.raises(RateLimited):
        handle_private_message(msg("help"), deliver=deliver)

    assert len(probe) == 1


def test_send_to_user_uses_digits_only(user, fake_channel):
    outbound.send_to_user(user, text="hello")
    outbound.send_to_user(user, text="look", image_url="https://x.test/a.png")

    assert fake_channel.sent == [
        {"type": "text", "to": PHONE, "text": "hello"},
        {"type": "image", "to": PHONE, "image_url": "https://x.test/a.png", "caption": "look"},
    ]


def test_send_to_user_skips_blocked_users(user, fake_channel):
    user.blocked = True

    outbound.send_to_user(user, text="hello")

    assert fake_channel.sent == []


@pytest.mark.parametrize("exc", [RateLimited(3), ChannelError(f"boom {PHONE} secret text")])
def test_send_to_user_swallows_channel_errors_logging_class_only(
    user, fake_channel, monkeypatch, caplog, exc
):
    def fail(to, text):
        raise exc

    monkeypatch.setattr(fake_channel, "send_text", fail)

    with caplog.at_level(logging.DEBUG):
        outbound.send_to_user(user, text="secret text")

    assert type(exc).__name__ in caplog.text
    assert PHONE not in caplog.text
    assert "secret text" not in caplog.text
