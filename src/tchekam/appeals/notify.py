"""Tell the appellant how the appeal was decided, within the 24 h reply window (ADR-011).

The decision task claims `notified_at`, then sends outside any lock if the window is open and
marks `delivered_at`. A claimed appeal that was not delivered (window closed, send failed, crash)
goes out in front of the reply to the user's next message. Never logged: statements, reasons.
"""

from django.conf import settings
from django.utils import timezone

from tchekam.conversations.models import BotUser, Conversation
from tchekam.conversations.outbound import send_to_user
from tchekam.conversations.router import Reply
from tchekam.conversations.service import HookResult, register_after_route_hook
from tchekam.i18n import t
from tchekam.reports.notify import window_open

from .models import Appeal

MAX_DELIVERED_PER_MESSAGE = 3


def render(appeal: Appeal, lang: str | None) -> str:
    if appeal.status == Appeal.Status.APPROVED:
        return t("appeal.notify.approved", lang)
    # Only the outcome is sent: the moderator's reason stays internal.
    parts = [t("appeal.notify.rejected", lang)]
    if settings.HELP_URL:
        parts.append(t("appeal.notify.more_help", lang, url=settings.HELP_URL))
    return "\n\n".join(parts)


def notify_decision(appeal_id: int) -> None:
    """Send or queue the decision message, at most once per claim."""
    appeal = Appeal.objects.select_related("appellant").filter(pk=appeal_id).first()
    user = appeal.appellant if appeal else None
    if appeal is None or user is None or user.blocked:
        return
    if appeal.status not in (Appeal.Status.APPROVED, Appeal.Status.REJECTED):
        return
    claimed = Appeal.objects.filter(pk=appeal_id, notified_at__isnull=True).update(
        notified_at=timezone.now()
    )
    if not claimed:
        return
    # The HTTP send happens after the claim has committed, never under a lock (ADR-017).
    if window_open(user) and send_to_user(user, text=render(appeal, user.language), defer=False):
        Appeal.objects.filter(pk=appeal_id, delivered_at__isnull=True).update(
            delivered_at=timezone.now()
        )


def deliver_pending(user: BotUser, conversation: Conversation, replies: list[Reply]) -> HookResult:
    rows = list(
        Appeal.objects.filter(
            appellant=user, notified_at__isnull=False, delivered_at__isnull=True
        ).order_by("decided_at", "pk")[:MAX_DELIVERED_PER_MESSAGE]
    )
    if not rows:
        return HookResult()
    ids = [r.pk for r in rows]

    def mark_delivered() -> None:
        Appeal.objects.filter(pk__in=ids, delivered_at__isnull=True).update(
            delivered_at=timezone.now()
        )

    return HookResult([Reply(render(r, user.language)) for r in rows], mark_delivered)


def register() -> None:
    register_after_route_hook(deliver_pending)
