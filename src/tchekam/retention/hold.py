"""Legal hold (ADR-013): what is held, and the audited admin toggles.

A hold is set on a report, a number (PhoneNumber) or a user (BotUser); Evidence also has its
own flag. A report is held if it, its reporter, any subject number or any of its evidence is
held. Retention skips anything held, and a held user cannot be deleted.
"""

from django.contrib import admin
from django.db.models import Q, QuerySet

from tchekam.conversations.models import BotUser
from tchekam.core.audit import audit
from tchekam.core.http import client_ip
from tchekam.identifiers.models import PhoneNumber
from tchekam.reports.keys import reporter_key_for
from tchekam.reports.models import Report


def held_reports() -> QuerySet:
    """Primary keys of every held report, as a subquery (use with pk__in / exclude).

    A subject number is held if the PhoneNumber is held or it is a held user's own number
    (held_phones). A minimised rejected report has no subjects left, only
    `subject_phone_keys`, so held numbers are matched there too: a hold placed after
    minimisation still protects the record.
    """
    phones = held_phones()
    held = Q(legal_hold=True) | Q(reporter__legal_hold=True) | Q(evidence__legal_hold=True)
    held |= Q(subjects__phone_number__legal_hold=True)
    held |= Q(subjects__phone_number__e164__in=phones)
    for e164 in phones:
        held |= Q(subject_phone_keys__contains=[reporter_key_for(e164)])
    return Report.objects.filter(held).values("pk")


def held_users() -> QuerySet:
    return BotUser.objects.filter(legal_hold=True).values("pk")


def held_numbers() -> QuerySet:
    return PhoneNumber.objects.filter(legal_hold=True).values("pk")


def held_phones() -> set[str]:
    """E.164 of every held number and held user (a user's number is held with them)."""
    users = BotUser.objects.filter(legal_hold=True).values_list("wa_phone", flat=True)
    numbers = PhoneNumber.objects.filter(legal_hold=True).values_list("e164", flat=True)
    return {*users, *numbers}


def set_legal_hold(queryset: QuerySet, on: bool, actor, ip: str | None = None) -> int:
    """Place or release the hold on each object; audits each actual change. Returns changes."""
    action = "retention.legal_hold.placed" if on else "retention.legal_hold.released"
    changed = 0
    for obj in queryset.exclude(legal_hold=on):
        type(obj).objects.filter(pk=obj.pk).update(legal_hold=on)
        audit(actor, action, obj, ip=ip)
        changed += 1
    return changed


def can_manage_legal_hold(user) -> bool:
    return user.has_perm("retention.manage_legal_hold")  # true for active superusers


@admin.action(
    description="Place on legal hold (retention deletes nothing)", permissions=["legal_hold"]
)
def place_legal_hold(modeladmin, request, queryset):
    n = set_legal_hold(queryset, True, request.user, client_ip(request))
    modeladmin.message_user(request, f"Legal hold placed on {n} record(s).")


@admin.action(description="Release legal hold", permissions=["legal_hold"])
def release_legal_hold(modeladmin, request, queryset):
    n = set_legal_hold(queryset, False, request.user, client_ip(request))
    modeladmin.message_user(request, f"Legal hold released on {n} record(s).")


class LegalHoldAdminMixin:
    """Adds the audited legal-hold actions, offered only with retention.manage_legal_hold."""

    actions = (place_legal_hold, release_legal_hold)

    def has_legal_hold_permission(self, request) -> bool:
        return can_manage_legal_hold(request.user)
