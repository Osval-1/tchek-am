"""Follow-up (c) of ISSUES.md Issue 20: a group event not ingested keeps no poster or media key."""

import pytest

from tchekam.messaging.models import InboundEvent

from .conftest import GROUP_JID, POSTER
from .test_intake import NOT_PRODUCT, PRODUCT, group_image, group_text

pytestmark = pytest.mark.django_db


def _scrubbed(message_id) -> bool:
    payload = InboundEvent.objects.get(message_id=message_id).payload
    stored = payload["data"]["messages"]
    digits = POSTER.lstrip("+")
    return (
        stored.get("scrubbed") is True
        and stored["message"] == {}
        and digits not in str(payload)
        and stored["key"]["remoteJid"] == GROUP_JID
    )


@pytest.fixture
def deliver(client, django_capture_on_commit_callbacks):
    from ..messaging.test_webhook import post

    def send(body):
        with django_capture_on_commit_callbacks(execute=True):
            assert post(client, body).status_code == 200

    return send


def test_unconsented_group_event_is_scrubbed(deliver, fake_channel):
    deliver(group_text())

    assert _scrubbed("MSG-GRP-1")


def test_text_in_a_partner_group_is_scrubbed(deliver, make_partner_group):
    make_partner_group(GROUP_JID)
    deliver(group_text())

    assert _scrubbed("MSG-GRP-1")


def test_opted_out_poster_event_is_scrubbed(deliver, make_partner_group):
    from tchekam.groups.models import GroupOptOut

    make_partner_group(GROUP_JID)
    GroupOptOut.objects.create(wa_phone=POSTER)
    deliver(group_image())

    assert _scrubbed("MSG-GRP-IMG-1")


@pytest.mark.parametrize("verdict", [PRODUCT, NOT_PRODUCT])
def test_image_event_is_scrubbed_once_the_ingest_job_is_done(
    deliver, make_partner_group, fake_channel, fake_llm, object_store, verdict
):
    from ..imaging.helpers import encode, structured_image

    make_partner_group(GROUP_JID)
    fake_channel.media["MSG-GRP-IMG-1"] = (encode(structured_image(4)), "image/png")
    fake_llm.responses["is_product_photo"] = [verdict]

    deliver(group_image())

    assert _scrubbed("MSG-GRP-IMG-1")
