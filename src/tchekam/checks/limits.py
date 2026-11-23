from django.conf import settings
from django.utils import timezone

from tchekam.conversations.models import BotUser

from .models import CheckLog


def check_allowed(user: BotUser) -> bool:
    """False once the user has used today's quota. The day is the Cameroonian calendar day."""
    day_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    used = CheckLog.objects.filter(user=user, created_at__gte=day_start).count()
    return used < settings.CHECKS_PER_DAY
