from django.conf import settings
from django.utils import timezone

from tchekam.conversations.models import BotUser

from .models import Report
from .weighting import reporter_is_limited, submitted_this_week


def daily_limit_reached(user: BotUser) -> bool:
    """True once the user has submitted REPORTS_PER_DAY reports today (Cameroonian calendar day)."""
    day_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    submitted = (
        Report.objects.filter(reporter=user, submitted_at__gte=day_start)
        .exclude(status=Report.Status.WITHDRAWN)
        .count()
    )
    return submitted >= settings.REPORTS_PER_DAY


def weekly_limit_reached(user: BotUser) -> bool:
    """Low-trust reporters (R3) may submit one report per rolling week."""
    return reporter_is_limited(user) and submitted_this_week(user)


def limit_notice(user: BotUser) -> tuple[str, dict[str, int]] | None:
    """Catalogue key and arguments for the refusal that applies to this user now, if any."""
    if daily_limit_reached(user):
        return "report.limit_reached", {"n": settings.REPORTS_PER_DAY}
    if weekly_limit_reached(user):
        return "report.limit_reached_weekly", {}
    return None
