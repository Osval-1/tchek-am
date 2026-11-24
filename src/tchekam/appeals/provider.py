"""What reputation reads about appeals (installed as its appeals hook in AppConfig.ready)."""

from django.db.models import Max

from tchekam.reputation.facts import AppealState

from .models import Appeal


def appeal_state(e164: str) -> AppealState:
    appeals = Appeal.objects.filter(phone_number__e164=e164)
    # The latest approved acquisition date wins: it describes the current owner.
    acquired = appeals.filter(status=Appeal.Status.APPROVED, kind=Appeal.Kind.NEW_TO_ME).aggregate(
        d=Max("number_acquired_at")
    )["d"]
    return AppealState(
        under_appeal=appeals.filter(status=Appeal.Status.OPEN).exists(),
        number_acquired_at=acquired,
    )
