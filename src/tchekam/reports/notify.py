"""Tell reporters how their report was decided (F5), within the channel safeguards (ADR-011).

A message is sent straight away only while the reporter's reply window is open (they wrote
within REPLY_WINDOW_HOURS). Otherwise, or when sending fails, it is kept as a
`PendingNotification` and goes out in front of the reply to the reporter's next message.
Never logged: the moderator's text, report text, numbers.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tchekam.conversations.models import BotUser, Conversation
from tchekam.conversations.outbound import send_to_user
from tchekam.conversations.router import Reply
from tchekam.conversations.service import HookResult, register_after_route_hook
from tchekam.i18n import t

from . import flow, needs_info
from .models import ModerationDecision, PendingNotification, Report

MAX_DELIVERED_PER_MESSAGE = 3
REJECT_KEYS = {
    "insufficient_evidence": "notify.rejected.insufficient_evidence",
    "duplicate": "notify.rejected.duplicate",
    "cannot_verify": "notify.rejected.cannot_verify",
}


def _reference(report: Report) -> str:
    return report.reference or f"#{report.pk}"


def _with_next_steps(body: str, lang: str | None) -> str:
    parts = [body, t("notify.next_steps", lang)]
    if settings.HELP_URL:
        parts.append(t("notify.more_help", lang, url=settings.HELP_URL))
    return "\n\n".join(parts)


def render(decision: ModerationDecision, lang: str | None, busy: bool = False) -> str:
    """The reporter's message for a decision: catalogue copy, plus the need_info question.

    `busy`: the reporter is in the middle of another flow, so need_info says how to answer.
    """
    report = decision.report
    ref = _reference(report)
    action = decision.action
    if action == ModerationDecision.Action.MERGE:
        target = report.merged_into
        approved = target is not None and target.status == Report.Status.APPROVED
        action = ModerationDecision.Action.APPROVE if approved else "merged_pending"
    if action == ModerationDecision.Action.APPROVE:
        return _with_next_steps(t("notify.approved", lang, reference=ref), lang)
    if action == ModerationDecision.Action.REJECT:
        # Only the category picks the wording: the moderator's free text is never forwarded.
        code = decision.reason.split(":", 1)[0].strip()
        key = REJECT_KEYS.get(code, "notify.rejected.generic")
        return _with_next_steps(t(key, lang, reference=ref), lang)
    if action == ModerationDecision.Action.NEED_INFO:
        return "\n".join(
            [
                t("notify.need_info.intro", lang, reference=ref),
                needs_info.quote(decision.reason, lang),
                "",
                t("notify.need_info.reply_busy" if busy else "notify.need_info.reply", lang),
            ]
        )
    if action == "merged_pending":
        return t("notify.merged_pending", lang, reference=ref)
    return t("notify.reopened", lang, reference=ref)


def _window_open(user: BotUser) -> bool:
    last = user.last_inbound_at
    return last is not None and timezone.now() - last <= timedelta(
        hours=settings.REPLY_WINDOW_HOURS
    )


def _queue(user: BotUser, decision: ModerationDecision) -> None:
    PendingNotification.objects.get_or_create(
        decision=decision, defaults={"user": user, "report": decision.report}
    )


def _free(conv: Conversation) -> bool:
    """Idle, or holding a prompt that has gone stale (the router would drop it anyway)."""
    expired = conv.expires_at is not None and conv.expires_at <= timezone.now()
    return conv.flow == Conversation.IDLE or expired


def _in_loop_for(conv: Conversation, report: Report) -> bool:
    return conv.flow == flow.NEEDS_INFO and conv.state.get("report_id") == report.pk


def notify_decision(report_id: int, decision_id: int) -> None:
    """Send or queue the message for one decision, at most once (claimed via notified_at)."""
    decision = (
        ModerationDecision.objects.select_related("report__reporter", "report__merged_into")
        .filter(pk=decision_id, report_id=report_id)
        .first()
    )
    user = decision.report.reporter if decision else None
    if decision is None or user is None or user.blocked:
        return
    asking = decision.action == ModerationDecision.Action.NEED_INFO
    with transaction.atomic():
        claimed = ModerationDecision.objects.filter(
            pk=decision.pk, notified_at__isnull=True
        ).update(notified_at=timezone.now())
        if not claimed:
            return
        conv = None
        if asking:
            # Locked so the reply that follows finds the loop already started.
            Conversation.objects.get_or_create(user=user)
            conv = Conversation.objects.select_for_update().get(user=user)
        if (
            asking
            and not Report.objects.filter(pk=report_id, status=Report.Status.NEEDS_INFO).exists()
        ):
            return  # the question is out of date: a later decision replaced it
        busy = conv is not None and not _free(conv)
        # The send is an HTTP call made while the Conversation row is locked (bounded by the
        # channel timeout). It happens inside the transaction so a crash rolls the claim back and
        # nothing is lost; the price is at-least-once: a commit failure after a successful send
        # makes the retry send the message again.
        if _window_open(user) and send_to_user(user, text=render(decision, user.language, busy)):
            if conv is not None and not busy:
                needs_info.enter(conv, decision.report, decision.created_at)
                conv.save()
            return
        _queue(user, decision)


def _start_loop_after_delivery(user: BotUser, report_id: int, since: datetime) -> None:
    """Only once the question reached the reporter: otherwise their next message would be taken
    as an answer to a question they never saw."""
    with transaction.atomic():
        conv = Conversation.objects.select_for_update().get(user=user)
        report = Report.objects.filter(pk=report_id, status=Report.Status.NEEDS_INFO).first()
        if report is not None and _free(conv):
            needs_info.enter(conv, report, since)
            conv.save()


def deliver_pending(user: BotUser, conversation: Conversation, replies: list[Reply]) -> HookResult:
    """After-route hook: queued notifications, oldest first, to put ahead of the routed replies.

    Rows are marked delivered only once the replies were actually sent (`on_delivered`).
    """
    rows = list(
        PendingNotification.objects.select_related("decision", "report__merged_into")
        .filter(user=user, delivered_at__isnull=True)
        .order_by("created_at", "pk")[:MAX_DELIVERED_PER_MESSAGE]
    )
    out: list[Reply] = []
    sent_ids: list[int] = []
    dropped_ids: list[int] = []
    loop: tuple[int, datetime] | None = None  # (report, asked at): starts once delivered
    for row in rows:
        decision, report = row.decision, row.report
        asking = decision.action == ModerationDecision.Action.NEED_INFO
        if asking and report.status != Report.Status.NEEDS_INFO:
            dropped_ids.append(row.pk)  # the question is out of date: a later decision replaced it
            continue
        starts_loop = asking and loop is None and _free(conversation)
        busy = asking and not starts_loop and not _in_loop_for(conversation, report)
        out.append(Reply(render(decision, user.language, busy)))
        sent_ids.append(row.pk)
        if starts_loop:
            loop = (report.pk, decision.created_at)
    now = timezone.now()
    PendingNotification.objects.filter(pk__in=dropped_ids).update(delivered_at=now)

    def mark_delivered() -> None:
        PendingNotification.objects.filter(pk__in=sent_ids, delivered_at__isnull=True).update(
            delivered_at=timezone.now()
        )
        if loop is not None:
            _start_loop_after_delivery(user, *loop)

    return HookResult(out, mark_delivered if sent_ids else None)


def register() -> None:
    register_after_route_hook(deliver_pending)
