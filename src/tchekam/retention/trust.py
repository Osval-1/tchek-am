"""Reporter trust that survives erasure (ADR-015, ADR-022), and the guard on deleting users.

Invariant (R3): losing or re-creating an account never raises the weight of a reporter's old
reports. The stored snapshot only ever goes down; lookups return at most the snapshot, and a
user who comes back on the same number starts at most at the snapshot (or at the weight their
old decided reports give), never at the 1.0 default. Later decisions recompute that account's
own trust by the usual formula, but that never lifts the snapshot.
"""

from collections.abc import Mapping

from django.db.models import ProtectedError
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.reports.keys import reporter_key_for
from tchekam.reports.models import Report
from tchekam.reports.weighting import _counts, trust_weight

from .models import ReporterTrust


def snapshot(user: BotUser) -> None:
    """Record the user's trust under their reporter key, if they ever reported.

    The snapshot only ever goes down: it is created with the current trust, and afterwards
    lowered when the current trust is lower, never raised. A later account on the same number
    (the same person back, or a recycled number's new owner) can therefore never lift the
    weight of reports whose link is already gone. The conditional UPDATE is atomic, so two
    concurrent writers cannot raise it either.
    """
    key = reporter_key_for(user.wa_phone)
    if not Report.objects.filter(reporter_key=key).exists():
        return  # never reported: nothing to weigh, nothing to keep
    weight = user.trust_weight
    _, created = ReporterTrust.objects.get_or_create(
        reporter_key=key, defaults={"trust_weight": weight}
    )
    if not created:
        ReporterTrust.objects.filter(reporter_key=key, trust_weight__gt=weight).update(
            trust_weight=weight, updated_at=timezone.now()
        )


def trust_for_keys(keys: frozenset[str]) -> Mapping[str, float]:
    """Trust for reports that lost their reporter link. Installed as reputation's provider.

    The lower of the stored snapshot and the trust of a live account on the same key (only
    some reports anonymised, or the person came back). Unknown keys are left out.
    """
    stored = dict(
        ReporterTrust.objects.filter(reporter_key__in=keys).values_list(
            "reporter_key", "trust_weight"
        )
    )
    live = dict(
        Report.objects.filter(reporter_key__in=keys, reporter__isnull=False).values_list(
            "reporter_key", "reporter__trust_weight"
        )
    )
    return {
        k: min(v for v in (stored.get(k), live.get(k)) if v is not None)
        for k in stored.keys() | live.keys()
    }


def before_user_delete(sender, instance: BotUser, **kwargs) -> None:
    """pre_delete on BotUser: refuse while on legal hold, else keep the trust first."""
    if instance.legal_hold:
        raise ProtectedError("This user is on legal hold.", {instance})
    snapshot(instance)


def seed_new_user(sender, instance: BotUser, created: bool, **kwargs) -> None:
    """post_save on BotUser: a returning number starts no higher than its history allows."""
    if not created:
        return
    candidates = []
    key = reporter_key_for(instance.wa_phone)
    stored = ReporterTrust.objects.filter(reporter_key=key).first()
    if stored is not None:
        candidates.append(stored.trust_weight)
    approved, rejected = _counts(instance)  # by reporter_key: includes the erased reports
    if approved or rejected:
        candidates.append(trust_weight(approved, rejected))
    weight = min(candidates, default=instance.trust_weight)
    if weight < instance.trust_weight:
        BotUser.objects.filter(pk=instance.pk).update(trust_weight=weight)
        instance.trust_weight = weight
