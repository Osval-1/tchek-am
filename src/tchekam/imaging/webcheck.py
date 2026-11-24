"""Cached, capped web reverse-image search: the one way anything in the app triggers a call.

Order matters: a cache hit is served before any cap is looked at (it costs nothing), then the
caps are checked and the call is reserved in one step, then the provider is called. Callers get
`None` for "did not run" (cap reached or provider failed) and a list, possibly empty, otherwise.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.core.storage import get_object_store

from .models import WebSearchResult, WebSearchUsage
from .web import WebMatch, get_web_search

logger = logging.getLogger(__name__)

CACHE_DAYS = 30
SIGNED_URL_TTL_SECONDS = 600  # long enough for the provider to fetch once, short enough to expire
_LOCK_KEY = 0x7C4E_CA11  # arbitrary app-wide advisory lock id for reserving provider calls

SUBMISSION = WebSearchUsage.Purpose.SUBMISSION
REPORT = WebSearchUsage.Purpose.REPORT


def cached_matches(sha256: str) -> list[WebMatch] | None:
    """The last stored result for an image whatever its age (for display), or None."""
    row = WebSearchResult.objects.filter(sha256=sha256).first()
    return [WebMatch.from_json(m) for m in row.matches] if row else None


def lookup(
    sha256: str, object_key: str, *, user: BotUser | None, purpose: str
) -> list[WebMatch] | None:
    """Matches for the image stored at `object_key`, from cache or one provider call.

    Report images (purpose=report) skip the per-user daily cap but never the monthly budget.
    """
    fresh_since = timezone.now() - timedelta(days=CACHE_DAYS)
    row = WebSearchResult.objects.filter(sha256=sha256, checked_at__gte=fresh_since).first()
    if row is not None:
        return [WebMatch.from_json(m) for m in row.matches]
    usage = _reserve(user, purpose)
    if usage is None:
        return None
    try:
        # Only a short-lived signed URL leaves the building: no user id, no phone number.
        url = get_object_store().signed_url(object_key, SIGNED_URL_TTL_SECONDS)
        matches = get_web_search().search(url)
    except Exception as exc:  # noqa: BLE001 - a failed search must not abort the caller
        usage.delete()  # providers do not bill failed searches; do not burn the cap on them
        logger.warning("web search not completed: %s", type(exc).__name__)
        return None
    WebSearchResult.objects.update_or_create(
        sha256=sha256,
        defaults={"matches": [m.to_json() for m in matches], "checked_at": timezone.now()},
    )
    return matches


def _reserve(user: BotUser | None, purpose: str) -> WebSearchUsage | None:
    """Check both caps and record the call atomically, so parallel tasks cannot overshoot."""
    now = timezone.localtime()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_KEY])
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if WebSearchUsage.objects.filter(created_at__gte=month_start).count() >= (
            settings.WEB_SEARCH_MONTHLY_BUDGET
        ):
            return None
        if purpose == SUBMISSION and user is not None:
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            used_today = WebSearchUsage.objects.filter(
                user=user, purpose=SUBMISSION, created_at__gte=day_start
            ).count()
            if used_today >= settings.WEB_SEARCH_PER_USER_DAY:
                return None
        return WebSearchUsage.objects.create(user=user, purpose=purpose)
