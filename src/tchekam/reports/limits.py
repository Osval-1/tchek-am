from django.conf import settings
from django.utils import timezone

from tchekam.conversations.models import BotUser

from .models import Report


def daily_limit_reached(user: BotUser) -> bool:
    """True once the user has submitted REPORTS_PER_DAY reports today (Cameroonian calendar day)."""
    day_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    submitted = (
        Report.objects.filter(reporter=user, submitted_at__gte=day_start)
        .exclude(status=Report.Status.WITHDRAWN)
        .count()
    )
    return submitted >= settings.REPORTS_PER_DAY
