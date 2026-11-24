"""WaSender `group_metadata`, cached: at most one provider call per group per day.

The provider allows 10 calls a minute and 500 a day per session (docs/integrations/wasender.md).
Only the subject and the member count are kept; the participant list (numbers of people who
never used the bot) is read for its length and dropped.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from tchekam.messaging.channel import get_channel

from .models import GroupMetadata

MAX_AGE = timedelta(days=1)


def group_metadata(group_jid: str) -> GroupMetadata:
    """The cached metadata, refreshed when older than a day. Raises ChannelError on failure."""
    GroupMetadata.objects.get_or_create(group_jid=group_jid)
    with transaction.atomic():
        # Row lock: concurrent callers wait and then reuse the fresh result instead of calling.
        row = GroupMetadata.objects.select_for_update().get(group_jid=group_jid)
        if row.fetched_at is not None and timezone.now() - row.fetched_at < MAX_AGE:
            return row
        data = get_channel().group_metadata(group_jid)
        subject = data.get("subject")
        participants = data.get("participants")
        row.subject = subject[:200] if isinstance(subject, str) else ""
        row.participant_count = len(participants) if isinstance(participants, list) else 0
        row.fetched_at = timezone.now()
        row.save(update_fields=["subject", "participant_count", "fetched_at"])
    return row
