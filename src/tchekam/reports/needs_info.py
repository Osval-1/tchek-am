"""Need-more-info loop (F4/F5): the reporter answers a moderator question, report goes back.

Conversation state: {"report_id", "pending": {message_id: entry}, "since": ISO time of the
moderator's question, "story_len": length of the story when the loop was entered}. Evidence
and story text are collected exactly as while drafting (see `flow.add_content`); DONE then
moves the report needs_info -> pending. There is deliberately no re-extraction: the moderator
sees the new evidence on the review page and can add subjects by hand.
"""

import unicodedata
from datetime import datetime

from tchekam.conversations.models import Conversation
from tchekam.conversations.router import Context, Reply, register_flow, say, start_flow
from tchekam.i18n import t

from . import flow
from .models import ModerationDecision, Report

MAX_QUESTION = 500
# WhatsApp formatting markers: stripped so a question cannot restyle the bot's own text.
_FORMATTING = str.maketrans("", "", "*_~`")


def clean_question(text: str) -> str:
    """Plain text, one non-empty line per row, capped at MAX_QUESTION characters."""
    kept = "".join(
        ch for ch in text.replace("\r", "\n") if ch == "\n" or unicodedata.category(ch)[0] != "C"
    ).translate(_FORMATTING)
    lines = [line.strip() for line in kept.splitlines() if line.strip()]
    return "\n".join(lines)[:MAX_QUESTION].strip()


def quote(text: str, lang: str | None) -> str:
    """The moderator's question as a WhatsApp quote block (a generic ask if nothing is left)."""
    cleaned = clean_question(text) or t("notify.need_info.generic_question", lang)
    return "\n".join(f"> {line}" for line in cleaned.splitlines())


def latest_question(report: Report) -> ModerationDecision | None:
    return (
        report.decisions.filter(action=ModerationDecision.Action.NEED_INFO)
        .order_by("-created_at", "-pk")
        .first()
    )


def enter(conv: Conversation, report: Report, since: datetime) -> None:
    """Start the loop for a report in needs_info; `since` is when the question was asked."""
    state = {
        "report_id": report.pk,
        "pending": {},
        "since": since.isoformat(),
        "story_len": len(report.story_text),
    }
    start_flow(conv, flow.NEEDS_INFO, state=state, ttl=flow.REPORT_TTL)


def resume(ctx: Context, carry: dict[str, str] | None) -> list[Reply] | None:
    """The report intent while a report waits for more information; None when none does."""
    report = (
        Report.objects.filter(reporter=ctx.user, status=Report.Status.NEEDS_INFO)
        .order_by("-last_activity_at", "-pk")
        .first()
    )
    if report is None:
        return None
    decision = latest_question(report)
    since = decision.created_at if decision else report.last_activity_at
    enter(ctx.conversation, report, since)
    question = quote(decision.reason if decision else "", ctx.lang)
    replies = say(
        ctx,
        "report.needs_info.resume",
        reference=report.reference or f"#{report.pk}",
        question=question,
    )
    if carry:  # the image or voice note that started this report is the first answer
        replies += flow.accept_media(ctx, report, carry["message_id"], carry["kind"])
    return replies


def _has_new_content(report: Report, state: dict) -> bool:
    since = datetime.fromisoformat(state["since"])
    return report.evidence.filter(created_at__gt=since).exists() or len(
        report.story_text
    ) > state.get("story_len", 0)


def _finish(ctx: Context, report: Report) -> list[Reply]:
    waiting, dropped = flow.recover_pending(ctx, report)
    if dropped:
        key = "report.files_lost_one" if dropped == 1 else "report.files_lost"
        return say(ctx, key, n=dropped)
    if waiting:
        return say(ctx, "report.still_processing")
    if not _has_new_content(report, ctx.conversation.state):
        return say(ctx, "report.needs_info.need_content")
    report.transition(Report.Status.PENDING, actor=None, reason="reporter answered")
    ctx.conversation.reset()
    return say(ctx, "report.needs_info.resubmitted", reference=report.reference or f"#{report.pk}")


def _handle(ctx: Context) -> list[Reply]:
    state = ctx.conversation.state
    report = Report.objects.filter(
        pk=state.get("report_id"), reporter=ctx.user, status=Report.Status.NEEDS_INFO
    ).first()
    if report is None:  # the moderator decided meanwhile
        ctx.conversation.reset()
        return say(ctx, "report.needs_info.not_waiting")
    command = flow.user_command(ctx)
    if command in flow.CANCEL_WORDS:
        # Not a withdrawal: the report stays in needs_info and can be answered later.
        ctx.conversation.reset()
        return say(ctx, "report.needs_info.cancelled")
    flow.touch(ctx, report)
    if command in flow.FINISH_WORDS:
        return _finish(ctx, report)
    return flow.add_content(ctx, report)


def register() -> None:
    register_flow(flow.NEEDS_INFO, _handle)
