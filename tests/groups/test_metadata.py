from datetime import timedelta

import pytest
from django.utils import timezone

from tchekam.groups.metadata import group_metadata
from tchekam.groups.models import GroupMetadata
from tchekam.messaging.channel import ChannelError

from .conftest import GROUP_JID

pytestmark = pytest.mark.django_db

META = {
    "subject": "Marché Mokolo",
    "owner": "237690000001@s.whatsapp.net",
    "participants": [{"jid": "237690000001@s.whatsapp.net"}, {"jid": "1@lid"}],
}


def test_first_call_fetches_and_caches_subject_and_count_only(fake_channel):
    fake_channel.groups[GROUP_JID] = META

    meta = group_metadata(GROUP_JID)

    assert (meta.subject, meta.participant_count) == ("Marché Mokolo", 2)
    assert fake_channel.metadata_calls == [GROUP_JID]
    row = GroupMetadata.objects.get()
    assert "237690000001" not in str(row.__dict__)  # no participant or owner numbers kept


def test_at_most_one_call_per_group_per_day(fake_channel):
    fake_channel.groups[GROUP_JID] = META
    group_metadata(GROUP_JID)
    fake_channel.groups[GROUP_JID] = {"subject": "Renamed", "participants": []}

    assert group_metadata(GROUP_JID).subject == "Marché Mokolo"
    assert fake_channel.metadata_calls == [GROUP_JID]

    GroupMetadata.objects.update(fetched_at=timezone.now() - timedelta(days=1, seconds=1))
    assert group_metadata(GROUP_JID).subject == "Renamed"
    assert fake_channel.metadata_calls == [GROUP_JID, GROUP_JID]


def test_groups_are_limited_separately(fake_channel):
    group_metadata("a@g.us")
    group_metadata("b@g.us")

    assert fake_channel.metadata_calls == ["a@g.us", "b@g.us"]


def test_provider_failure_raises_and_keeps_the_previous_cache(fake_channel, monkeypatch):
    fake_channel.groups[GROUP_JID] = META
    group_metadata(GROUP_JID)
    GroupMetadata.objects.update(fetched_at=timezone.now() - timedelta(days=2))

    def broken(jid):
        raise ChannelError("WaSender groups: HTTP 500")

    monkeypatch.setattr(fake_channel, "group_metadata", broken)
    with pytest.raises(ChannelError):
        group_metadata(GROUP_JID)

    assert GroupMetadata.objects.get().subject == "Marché Mokolo"


def test_odd_provider_shapes_are_tolerated(fake_channel):
    fake_channel.groups[GROUP_JID] = {"subject": None, "participants": "nope"}

    meta = group_metadata(GROUP_JID)

    assert (meta.subject, meta.participant_count) == ("", 0)
