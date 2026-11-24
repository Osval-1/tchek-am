import pytest

from tchekam.conversations.models import BotUser
from tchekam.conversations.outbound import send_to_user

pytestmark = pytest.mark.django_db


def test_sends_to_the_users_number(fake_channel):
    user = BotUser.objects.create(wa_phone="+237670000001")

    assert send_to_user(user, text="hi") is True
    assert fake_channel.sent == [{"type": "text", "to": "237670000001", "text": "hi"}]


@pytest.mark.parametrize("image_url", [None, "https://x/img.jpg"])
def test_never_targets_a_group_and_never_raises(fake_channel, image_url):
    # Unsaved: wa_phone (max 20 chars, created from sender digits) cannot even hold a group JID.
    user = BotUser(pk=1, wa_phone="+120363000000000001@g.us")

    assert send_to_user(user, text="hi", image_url=image_url) is False
    assert fake_channel.sent == []
