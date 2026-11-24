"""Group listening (F8, ADR-012): partner groups, the leave log, poster opt-outs.

Group identity is private: nothing here is ever shown to bot users (search results carry no
group, see imaging.search.Match).
"""

from django.conf import settings
from django.db import models


class PartnerGroup(models.Model):
    """A WhatsApp selling group whose admin consented to group listening.

    Only an ACTIVE group is listened to. PAUSED and LEFT groups are ignored without leaving:
    the bot only leaves groups that have no PartnerGroup at all. Consent fields are NOT NULL,
    so a group cannot exist without who recorded the consent and when the notice was confirmed.
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        PAUSED = "paused"
        LEFT = "left"

    group_jid = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    admin_phone = models.CharField(max_length=20)  # E.164 of the consenting admin
    consent_at = models.DateTimeField()
    # PROTECT: a consent record must keep who recorded it (deactivate staff, never delete).
    consent_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    notice_confirmed_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"PartnerGroup#{self.pk} ({self.status})"


class UnconsentedGroupLeave(models.Model):
    """The one leave the bot made for a group without consent. Unique jid = at most one leave."""

    group_jid = models.CharField(max_length=100, unique=True)
    left_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"UnconsentedGroupLeave#{self.pk}"


class GroupOptOut(models.Model):
    """A poster who sent STOP GROUP. Their group images are discarded before download.

    Keyed on the WhatsApp number as "+<digits>" (the BotUser.wa_phone convention), so the
    check needs no PhoneNumber row and works for any country code.
    """

    wa_phone = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"GroupOptOut#{self.pk}"  # never the number: it ends up in logs and admin lists


class GroupMetadata(models.Model):
    """Cached `group_metadata` result: at most one provider call per group per day.

    Only the subject and the member count are kept, never the participant list.
    """

    group_jid = models.CharField(max_length=100, unique=True)
    subject = models.CharField(max_length=200, blank=True)
    participant_count = models.PositiveIntegerField(default=0)
    fetched_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"GroupMetadata#{self.pk}"
