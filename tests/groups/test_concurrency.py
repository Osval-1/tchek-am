"""Races that need real transactions on separate connections."""

import threading
import time

import pytest
from django.db import connection

from tchekam.groups.intake import handle_group_message
from tchekam.groups.models import UnconsentedGroupLeave
from tchekam.messaging.parser import parse_wasender_payload

from .conftest import GROUP_JID, load


def _msg(message_id):
    body = load("group_text")
    body["data"]["messages"]["key"]["id"] = message_id
    return parse_wasender_payload(body)


@pytest.mark.django_db(transaction=True)
def test_concurrent_deliveries_from_an_unconsented_group_leave_once(fake_channel, monkeypatch):
    calls = []
    original = fake_channel.leave_group

    def slow_leave(jid):
        calls.append(jid)
        time.sleep(0.3)  # hold the claim open while the other delivery arrives
        original(jid)

    monkeypatch.setattr(fake_channel, "leave_group", slow_leave)
    errors = []

    def run(message_id):
        try:
            handle_group_message(_msg(message_id))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(f"MSG-{i}",)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert calls == [GROUP_JID]
    assert UnconsentedGroupLeave.objects.count() == 1
