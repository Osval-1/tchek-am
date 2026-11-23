"""Report flow, part 1 (F4): start a draft, collect evidence, hand over to extraction.

Handlers run inside the router's transaction with the Conversation row locked, so they only
do light database work. Downloads, speech-to-text and AI run in `reports.tasks`, queued with
`Context.enqueue_after` so they start after the commit. Tasks come back here through
`present_for_confirmation`, `ask_for_details` and `analysis_failed`.

Conversation state while collecting: {"report_id": int, "pending": {message_id: entry}}, where
entry is {"t": queued_at, "kind": "image"|"audio", "retried": bool}; plus "extracting_since"
(ISO timestamp) while step is EXTRACTING.
The story lives on `Report.story_text`, so it survives a MENU or an expired conversation.
"""

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tchekam.conversations.models import BotUser, Conversation
from tchekam.conversations.outbound import send_to_user
from tchekam.conversations.router import (
    PROMPT_TTL,
    Context,
    Reply,
    normalize,
    register_flow,
    register_intent,
    say,
    start_flow,
)
from tchekam.core import redact
from tchekam.i18n import t
from tchekam.identifiers.models import get_or_create_phone
from tchekam.identifiers.phone import normalize_cm_number

from .limits import daily_limit_reached
from .models import Evidence, Report, ReportSubject

logger = logging.getLogger(__name__)

COLLECT = "report_collect"
RESUME = "report_resume_choice"
DETAILS = "report_await_details"
CONFIRM = "report_confirm"  # handled in confirm.py
EXTRACTING = "extracting"  # step of COLLECT while reports.extract runs

REPORT_TTL = timedelta(hours=24)  # from the last activity; after that, resume is offered
RESUME_WINDOW = timedelta(days=7)
MAX_ITEMS = 10
MAX_STORY = 4000
MAX_STORY_PART = 2000
MAX_TYPED_NUMBERS = 3
# A queued file whose task has not reported back after this long is re-queued once on DONE,
# then dropped on a later DONE (the user is asked to resend it).
PENDING_STALE = timedelta(minutes=10)
# An extraction still running after this long is presumed lost; DONE re-queues it.
EXTRACT_STALE = timedelta(minutes=10)
FINISH_WORDS = frozenset({"fini", "termine", "done", "finish", "1"})
CANCEL_WORDS = frozenset({"cancel", "annuler"})
MEDIA_KINDS = frozenset({"image", "audio"})
MAX_AMOUNT = 2_147_483_647  # PositiveIntegerField

_DIGITS = re.compile(r"\d+")
# Digit runs are bounded so int() below can never see thousands of digits.
_AMOUNT = re.compile(r"(?<!\d)(\d{1,3}(?:[ .,]\d{3}){1,4}|\d{1,15})(?!\d)")


# Shared helpers -------------------------------------------------------------------------------


def item_counts_text(report_id: int, lang: str | None) -> str:
    """'2 images, 1 voice note' from the stored evidence of a report."""
    rows = Evidence.objects.filter(report_id=report_id)
    voice = rows.filter(kind=Evidence.Kind.VOICE).count()
    images = rows.count() - voice
    parts = []
    if images:
        key = "report.count.image_one" if images == 1 else "report.count.image"
        parts.append(t(key, lang, n=images))
    if voice:
        key = "report.count.voice_one" if voice == 1 else "report.count.voice"
        parts.append(t(key, lang, n=voice))
    return ", ".join(parts) or t("report.count.none", lang)


def user_command(ctx: Context) -> str:
    return normalize(ctx.msg.text) if ctx.msg.kind == "text" else ""


def current_draft(user: BotUser, report_id: Any) -> Report | None:
    return Report.objects.filter(pk=report_id, reporter=user, status=Report.Status.DRAFT).first()


def touch(ctx: Context, report: Report) -> None:
    """Every step keeps the draft and the conversation alive for another 24 h."""
    now = timezone.now()
    report.last_activity_at = now
    Report.objects.filter(pk=report.pk).update(last_activity_at=now)
    ctx.conversation.expires_at = now + REPORT_TTL


def _enter_collect(conv: Conversation, report_id: int) -> None:
    start_flow(conv, COLLECT, state={"report_id": report_id, "pending": {}}, ttl=REPORT_TTL)


def cancel(ctx: Context, report: Report) -> list[Reply]:
    report.transition(Report.Status.WITHDRAWN, reason="cancelled by reporter")
    ctx.conversation.reset()
    return say(ctx, "report.cancelled")


def lost_draft(ctx: Context) -> list[Reply]:
    """The flow points at a report that is no longer a draft: start over."""
    ctx.conversation.reset()
    return _start_report(ctx)


# Start and resume -----------------------------------------------------------------------------


def _carried_media(ctx: Context) -> dict[str, str] | None:
    """The image or voice note that started the report, to add as its first item."""
    if ctx.extra.get("image_msg_id"):  # image_choice "2": the image came one message earlier
        return {"message_id": ctx.extra["image_msg_id"], "kind": "image"}
    if ctx.msg.kind in MEDIA_KINDS:  # a voice note sent with no flow
        return {"message_id": ctx.msg.message_id, "kind": ctx.msg.kind}
    return None


def _start_report(ctx: Context) -> list[Reply]:
    if daily_limit_reached(ctx.user):  # refuse early, before the user gathers evidence
        return say(ctx, "report.limit_reached", n=settings.REPORTS_PER_DAY)
    carry = _carried_media(ctx)
    recent = timezone.now() - RESUME_WINDOW
    draft = (
        Report.objects.filter(
            reporter=ctx.user, status=Report.Status.DRAFT, last_activity_at__gte=recent
        )
        .order_by("-last_activity_at", "-pk")
        .first()
    )
    if draft is not None:
        state = {"report_id": draft.pk, "carry": carry}
        start_flow(ctx.conversation, RESUME, state=state, ttl=PROMPT_TTL)
        return say(ctx, "report.resume_choice", items=item_counts_text(draft.pk, ctx.lang))
    return _new_report(ctx, carry)


def _new_report(ctx: Context, carry: dict[str, str] | None) -> list[Reply]:
    report = Report.objects.create(reporter=ctx.user)
    _enter_collect(ctx.conversation, report.pk)
    replies = say(ctx, "report.instructions")
    if carry:
        replies += _accept_media(ctx, report, carry["message_id"], carry["kind"])
    return replies


def _resume_choice(ctx: Context) -> list[Reply]:
    state = ctx.conversation.state
    carry = state.get("carry")
    draft = current_draft(ctx.user, state.get("report_id"))
    if draft is None:
        return _new_report(ctx, carry)
    choice = user_command(ctx)
    if choice == "1":
        _enter_collect(ctx.conversation, draft.pk)
        touch(ctx, draft)
        replies = say(ctx, "report.resumed", items=item_counts_text(draft.pk, ctx.lang))
        if carry:
            replies += _accept_media(ctx, draft, carry["message_id"], carry["kind"])
        return replies
    if choice == "2":
        draft.transition(Report.Status.WITHDRAWN, reason="replaced by a new report")
        return _new_report(ctx, carry)
    return say(ctx, "report.resume_choice", items=item_counts_text(draft.pk, ctx.lang))


# Collect --------------------------------------------------------------------------------------


def _pending(conv: Conversation) -> dict[str, dict[str, Any]]:
    return conv.state.setdefault("pending", {})


def _ingest_after(ctx: Context, report: Report, message_id: str, kind: str) -> None:
    ctx.enqueue_after("reports.ingest_media", report_id=report.pk, message_id=message_id, kind=kind)


def _accept_media(ctx: Context, report: Report, message_id: str, kind: str) -> list[Reply]:
    """Count the item against the limit now; download and store it in a task after commit."""
    pending = _pending(ctx.conversation)
    if message_id in pending:
        return []
    if Evidence.objects.filter(report=report).count() + len(pending) >= MAX_ITEMS:
        return say(ctx, "report.limit_items")
    pending[message_id] = {"t": time.time(), "kind": kind, "retried": False}
    _ingest_after(ctx, report, message_id, kind)
    return []


def _recover_pending(ctx: Context, report: Report) -> tuple[bool, int]:
    """On DONE: (still waiting, files given up on).

    A file whose job has not reported back within PENDING_STALE is re-queued once (ingestion is
    idempotent per message); if it is stale again after that, it is dropped.
    """
    now = time.time()
    waiting, dropped = False, 0
    pending = _pending(ctx.conversation)
    for message_id, entry in list(pending.items()):
        if now - entry["t"] <= PENDING_STALE.total_seconds():
            waiting = True
        elif entry.get("retried"):
            del pending[message_id]
            dropped += 1
        else:
            entry.update(t=now, retried=True)
            _ingest_after(ctx, report, message_id, entry["kind"])
            waiting = True
    return waiting, dropped


def _append_story(report: Report, text: str) -> bool:
    """Add a message to the story within the caps. False when the story is already full."""
    current = report.story_text
    if len(current) >= MAX_STORY:
        return False
    part = text.strip()[:MAX_STORY_PART]
    if part:
        report.story_text = (f"{current}\n{part}" if current else part)[:MAX_STORY]
        Report.objects.filter(pk=report.pk).update(story_text=report.story_text)
    return True


def _start_extraction(ctx: Context, report: Report) -> None:
    ctx.conversation.step = EXTRACTING
    ctx.conversation.state["extracting_since"] = timezone.now().isoformat()
    ctx.enqueue_after("reports.extract", report_id=report.pk)


def _finish(ctx: Context, report: Report) -> list[Reply]:
    waiting, dropped = _recover_pending(ctx, report)
    if dropped:
        # Stay collecting so the files can be resent; the next DONE proceeds as usual.
        key = "report.files_lost_one" if dropped == 1 else "report.files_lost"
        return say(ctx, key, n=dropped)
    if waiting:
        return say(ctx, "report.still_processing")
    if not report.story_text.strip() and not report.evidence.exists():
        return say(ctx, "report.need_one_item")
    _start_extraction(ctx, report)
    return say(ctx, "report.analysing")


def _extracting(ctx: Context, report: Report, command: str) -> list[Reply]:
    """While extraction runs. DONE after EXTRACT_STALE re-queues a job presumed lost."""
    since = ctx.conversation.state.get("extracting_since")
    started = datetime.fromisoformat(since) if since else None
    if command in FINISH_WORDS and (started is None or timezone.now() - started > EXTRACT_STALE):
        _start_extraction(ctx, report)  # idempotent: unchanged evidence is not billed twice
    return say(ctx, "report.analysis_wait")


def _collect(ctx: Context) -> list[Reply]:
    report = current_draft(ctx.user, ctx.conversation.state.get("report_id"))
    if report is None:
        return lost_draft(ctx)
    command = user_command(ctx)
    if command in CANCEL_WORDS:
        return cancel(ctx, report)
    if ctx.conversation.step == EXTRACTING:
        return _extracting(ctx, report, command)
    touch(ctx, report)
    if command in FINISH_WORDS:
        return _finish(ctx, report)

    msg = ctx.msg
    if msg.kind in MEDIA_KINDS:
        if msg.text:  # an image caption is part of the story
            _append_story(report, msg.text)
        return _accept_media(ctx, report, msg.message_id, msg.kind)
    if msg.kind in ("text", "contact") and (msg.text or "").strip():
        # Anything typed here is story, including a number: it is not a number check.
        if not _append_story(report, msg.text or ""):
            return say(ctx, "report.story_full")
        return say(ctx, "report.story_noted")
    return say(ctx, "report.unsupported_item")


# Typed details fallback -----------------------------------------------------------------------


def _joinable(text: str, end: int, start: int) -> bool:
    return start - end == 1 and text[end] in " .-"


def parse_details(text: str) -> tuple[list[str], int | None]:
    """Seller numbers (E.164) and an amount in XAF from a typed reply like '677123456 25000'.

    A number typed alone may be a fixed line; inside a sentence only mobiles count. Digit
    groups that form a number are removed before the amount is read, so they never become one.
    """
    alone = normalize_cm_number(text.strip())
    if alone:
        return [alone], None
    groups = [(m.start(), m.end(), m.group()) for m in _DIGITS.finditer(text)]
    numbers: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(groups):
        joined, best = "", None
        for j in range(i, len(groups)):
            if j > i and not _joinable(text, groups[j - 1][1], groups[j][0]):
                break
            joined += groups[j][2]
            if len(joined) > 14:  # "00237" + 9 digits is the longest written form
                break
            e164 = normalize_cm_number(joined)
            if e164 and e164.startswith("+2376"):  # Cameroonian mobiles all start with 6
                best = (j, e164)
        if best is None:
            i += 1
            continue
        j, e164 = best
        numbers.append(e164)
        spans.append((groups[i][0], groups[j][1]))
        i = j + 1

    rest = list(text)
    for start, end in spans:
        rest[start:end] = "|" * (end - start)  # a barrier, so neighbours do not merge
    amount = None
    for match in _AMOUNT.finditer("".join(rest)):
        value = int(re.sub(r"\D", "", match.group(1)))
        if 0 < value <= MAX_AMOUNT:
            amount = value
            break
    return list(dict.fromkeys(numbers)), amount


def _await_details(ctx: Context) -> list[Reply]:
    state = ctx.conversation.state
    report = current_draft(ctx.user, state.get("report_id"))
    if report is None:
        return lost_draft(ctx)
    if user_command(ctx) in CANCEL_WORDS:
        return cancel(ctx, report)
    touch(ctx, report)
    text = ctx.msg.text if ctx.msg.kind == "text" else ""
    numbers, amount = parse_details(text or "")
    if amount is not None:
        report.amount_xaf = amount
        Report.objects.filter(pk=report.pk).update(amount_xaf=amount)
    if not numbers and not state.get("asked_again"):
        state["asked_again"] = True
        return say(ctx, "report.ask_details_again")
    # Without a number we carry on anyway; the confirm step insists on one.
    for e164 in numbers[:MAX_TYPED_NUMBERS]:
        ReportSubject.objects.get_or_create(
            report=report,
            phone_number=get_or_create_phone(e164),
            role=ReportSubject.Role.SELLER,
            source=ReportSubject.Source.USER,
            defaults={"confirmed": False},
        )
    return [Reply(enter_confirmation(ctx.conversation, report, ctx.lang))]


# Handover from tasks --------------------------------------------------------------------------


def enter_confirmation(conv: Conversation, report: Report, lang: str | None) -> str:
    """Move the conversation to the confirm step; returns the message to send."""
    from . import confirm  # confirm builds on this module, so it is imported late

    return confirm.enter(conv, report, lang)


def _from_extracting(report: Report, enter: Callable[[Conversation, str | None], str]) -> None:
    """Leave the extracting step and message the reporter, if they are still waiting on it.

    A conversation that moved on (MENU, cancel, a newer report) is left alone; a duplicate
    task run finds the step already left and does nothing.
    """
    user = report.reporter
    if user is None:
        return
    with transaction.atomic():
        conv = Conversation.objects.select_for_update().filter(user=user).first()
        if (
            conv is None
            or conv.flow != COLLECT
            or conv.step != EXTRACTING
            or conv.state.get("report_id") != report.pk
        ):
            return
        text = enter(conv, user.language)
        conv.save()
    send_to_user(user, text=text)


def present_for_confirmation(report: Report) -> None:
    _from_extracting(report, lambda conv, lang: enter_confirmation(conv, report, lang))


def ask_for_details(report: Report) -> None:
    def enter(conv: Conversation, lang: str | None) -> str:
        start_flow(conv, DETAILS, state={"report_id": report.pk}, ttl=REPORT_TTL)
        return t("report.ask_details", lang)

    _from_extracting(report, enter)


def analysis_failed(report: Report) -> None:
    """Back to collecting with a "send DONE again" message. Never raises."""

    def enter(conv: Conversation, lang: str | None) -> str:
        conv.step = ""
        conv.state.pop("extracting_since", None)
        return t("report.analysis_failed", lang)

    try:
        _from_extracting(report, enter)
    except Exception as exc:  # the stale-DONE retry in _extracting is the last resort
        logger.warning("analysis_failed: report %s: %s", redact(report.pk), type(exc).__name__)


def register() -> None:
    register_intent("report", _start_report)
    register_flow(COLLECT, _collect)
    register_flow(RESUME, _resume_choice)
    register_flow(DETAILS, _await_details)
    from . import confirm

    confirm.register()
