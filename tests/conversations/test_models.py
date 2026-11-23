import pytest
from django.db import IntegrityError

from tchekam.conversations.models import BotUser, Conversation


@pytest.mark.django_db
def test_bot_user_defaults():
    user = BotUser.objects.create(wa_phone="+237670000001")

    assert user.language is None
    assert user.trust_weight == 1.0
    assert user.blocked is False
    assert user.training_opt_in is False
    assert user.last_inbound_at is None


@pytest.mark.django_db
def test_wa_phone_is_unique():
    BotUser.objects.create(wa_phone="+237670000001")

    with pytest.raises(IntegrityError):
        BotUser.objects.create(wa_phone="+237670000001")


@pytest.mark.django_db
def test_str_does_not_leak_the_phone_number():
    assert "670000001" not in str(BotUser.objects.create(wa_phone="+237670000001"))


@pytest.mark.django_db
def test_conversation_defaults_and_reset():
    user = BotUser.objects.create(wa_phone="+237670000001")
    conv = Conversation.objects.create(user=user)
    assert (conv.flow, conv.step, conv.state) == ("idle", "", {})

    conv.flow, conv.step, conv.state = "report", "ask_amount", {"a": 1}
    conv.reset()

    assert (conv.flow, conv.step, conv.state, conv.expires_at) == ("idle", "", {}, None)
