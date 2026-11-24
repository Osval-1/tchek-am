"""Reporter trust (R3): a smoothed approval rate, recomputed after every moderation decision."""

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from tchekam.conversations.models import BotUser

from .keys import reporter_key_for
from .models import Report, ReportSubject

LIMIT_BELOW_WEIGHT = 0.3
LIMIT_MIN_REJECTIONS = 3
LIMITED_WINDOW = timedelta(days=7)


def trust_weight(approved: int, rejected: int) -> float:
    """Laplace smoothing: a newcomer starts at 0.5 and no one reaches 0 or 1."""
    return (approved + 1) / (approved + rejected + 2)


def is_limited(weight: float, rejected: int) -> bool:
    return weight < LIMIT_BELOW_WEIGHT and rejected >= LIMIT_MIN_REJECTIONS


def _counts(user: BotUser) -> tuple[int, int]:
    # By reporter_key as well as the FK: retention drops the FK from approved reports after
    # 36 months (ISSUES.md Issue 24), and that must not lower the reporter's trust.
    mine = Q(reporter=user) | Q(reporter_key=reporter_key_for(user.wa_phone))
    counts = dict(
        Report.objects.filter(mine)
        .filter(status__in=[Report.Status.APPROVED, Report.Status.REJECTED])
        .values_list("status")
        .annotate(n=Count("id"))
    )
    return counts.get(Report.Status.APPROVED, 0), counts.get(Report.Status.REJECTED, 0)


def recompute(user: BotUser) -> set[str]:
    """Update the stored weight from current report statuses (so a reopen undoes a rejection).

    Call inside the decision's transaction. Returns the numbers whose cached band must be
    invalidated after commit: the weight feeds the independence count of every number this
    reporter has live reports about.
    """
    # Locked so two concurrent decisions on one reporter's reports cannot overwrite each other.
    row = BotUser.objects.select_for_update().get(pk=user.pk)
    weight = trust_weight(*_counts(row))
    if weight == row.trust_weight:
        return set()
    row.trust_weight = weight
    row.save(update_fields=["trust_weight"])
    user.trust_weight = weight
    live = [Report.Status.PENDING, Report.Status.NEEDS_INFO, Report.Status.APPROVED]
    return set(
        ReportSubject.objects.filter(
            report__reporter=row, report__status__in=live, phone_number__isnull=False
        ).values_list("phone_number__e164", flat=True)
    )


def reporter_is_limited(user: BotUser) -> bool:
    return is_limited(user.trust_weight, _counts(user)[1])


def submitted_this_week(user: BotUser) -> bool:
    since = timezone.now() - LIMITED_WINDOW
    return (
        Report.objects.filter(reporter=user, submitted_at__gte=since)
        .exclude(status=Report.Status.WITHDRAWN)
        .exists()
    )
