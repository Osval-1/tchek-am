"""Appeal flow (F6): chat steps from "I want to contest" to a submitted appeal.

Only the sender's own number can be appealed: it comes from the WhatsApp sender, and no number
typed anywhere in the flow is ever read as a target. Steps (Conversation.step):
KIND (1 wrong / 2 new to me) -> MONTH (only for 2) -> STATEMENT -> EVIDENCE (images and voice
notes, stored as-is, no transcription) -> DONE submits, CANCEL aborts.
Conversation state: {"kind", "acquired" (ISO first of month), "appeal_id", "pending": {id: entry}}.
The Appeal row is created as a draft when the statement step starts, so evidence has a parent.
"""

import time
from datetime import date, timedelta
from typing import Any

from django.utils import timezone

from tchekam.conversations.router import (
    Context,
    Reply,
    normalize,
    register_flow,
    register_intent,
    say,
    start_flow,
)
from tchekam.identifiers.models import PhoneNumber, get_or_create_phone
from tchekam.identifiers.phone import normalize_cm_number
from tchekam.reputation.service import band_for_phone

from . import service
from .dates import parse_acquired_month
from .models import Appeal
from .service import MAX_STATEMENT, Refusal

FLOW = "appeal"
KIND, MONTH, STATEMENT, EVIDENCE = "kind", "month", "statement", "evidence"
TTL = timedelta(hours=2)  # from the last step
PENDING_STALE = timedelta(minutes=10)  # a queued file that never reported back is dropped
MAX_ITEMS = 5
MEDIA_KINDS = frozenset({"image", "audio"})
FINISH_WORDS = frozenset({"fini", "termine", "done", "finish"})
CANCEL_WORDS = frozenset({"cancel", "annuler"})
REFUSALS = {
    Refusal.ALREADY_OPEN: "appeal.already_open",
    Refusal.NUMBER_BUSY: "appeal.number_busy",
    Refusal.LIMIT: "appeal.limit_reached",
}


def _keep_alive(ctx: Context) -> None:
    ctx.conversation.expires_at = timezone.now() + TTL


def _command(ctx: Context) -> str:
    return normalize(ctx.msg.text) if ctx.msg.kind == "text" else ""


def start(ctx: Context) -> list[Reply]:
    """Intent "appeal": check that this sender can appeal their own number, then ask the kind."""
    own = normalize_cm_number(ctx.user.wa_phone)
    if own is None:
        return say(ctx, "appeal.cm_only")
    # A number typed with the keyword is only ever compared, never appealed.
    if any(n != own for n in ctx.extra.get("typed_numbers", [])):
        return say(ctx, "appeal.own_number_only")
    phone = PhoneNumber.objects.filter(e164=own).first()
    result = band_for_phone(own)
    if phone is None or (result.band == "green" and not result.under_appeal):
        return say(ctx, "appeal.nothing")
    if refusal := service.refusal_for(ctx.user, phone.pk):
        return say(ctx, REFUSALS[refusal])
    for draft_id in Appeal.objects.filter(
        appellant=ctx.user, status=Appeal.Status.DRAFT
    ).values_list("pk", flat=True):
        ctx.enqueue_after("appeals.discard_draft", appeal_id=draft_id)
    start_flow(ctx.conversation, FLOW, step=KIND, ttl=TTL)
    return say(ctx, "appeal.choose_kind")


def _handle(ctx: Context) -> list[Reply]:
    conv = ctx.conversation
    command = _command(ctx)
    if command in CANCEL_WORDS:
        return _cancel(ctx)
    _keep_alive(ctx)
    if conv.step == KIND:
        return _kind(ctx, command)
    if conv.step == MONTH:
        return _month(ctx)
    if conv.step == STATEMENT:
        return _statement(ctx)
    if conv.step == EVIDENCE:
        return _evidence(ctx, command)
    conv.reset()  # a step from an older deploy
    return start(ctx)


def _cancel(ctx: Context) -> list[Reply]:
    draft_id = ctx.conversation.state.get("appeal_id")
    if draft_id:
        ctx.enqueue_after("appeals.discard_draft", appeal_id=draft_id)
    ctx.conversation.reset()
    return say(ctx, "appeal.cancelled")


def _kind(ctx: Context, command: str) -> list[Reply]:
    if command == "1":
        ctx.conversation.state["kind"] = Appeal.Kind.WRONG
        return _begin_statement(ctx)
    if command == "2":
        ctx.conversation.state["kind"] = Appeal.Kind.NEW_TO_ME
        ctx.conversation.step = MONTH
        return say(ctx, "appeal.ask_month")
    return say(ctx, "appeal.choose_kind")


def _month(ctx: Context) -> list[Reply]:
    text = ctx.msg.text if ctx.msg.kind == "text" else ""
    acquired = parse_acquired_month(text or "", timezone.localdate())
    if acquired is None:
        return say(ctx, "appeal.month_invalid")
    ctx.conversation.state["acquired"] = acquired.isoformat()
    return _begin_statement(ctx)


def _begin_statement(ctx: Context) -> list[Reply]:
    state = ctx.conversation.state
    acquired = date.fromisoformat(state["acquired"]) if state.get("acquired") else None
    own = normalize_cm_number(ctx.user.wa_phone)
    appeal = Appeal.objects.create(
        phone_number=get_or_create_phone(own),
        appellant=ctx.user,
        kind=state["kind"],
        number_acquired_at=acquired,
    )
    state["appeal_id"] = appeal.pk
    state["pending"] = {}
    ctx.conversation.step = STATEMENT
    return say(ctx, "appeal.ask_statement", n=MAX_STATEMENT)


def _draft(ctx: Context) -> Appeal | None:
    return Appeal.objects.filter(
        pk=ctx.conversation.state.get("appeal_id"),
        appellant=ctx.user,
        status=Appeal.Status.DRAFT,
    ).first()


def _lost(ctx: Context) -> list[Reply]:
    ctx.conversation.reset()
    return say(ctx, "appeal.lost")


def _statement(ctx: Context) -> list[Reply]:
    appeal = _draft(ctx)
    if appeal is None:
        return _lost(ctx)
    text = (ctx.msg.text or "").strip() if ctx.msg.kind == "text" else ""
    if not text:
        return say(ctx, "appeal.ask_statement", n=MAX_STATEMENT)
    if len(text) > MAX_STATEMENT:
        return say(ctx, "appeal.statement_too_long", n=MAX_STATEMENT)
    # Whatever is typed here is the statement, including a number: never a target.
    Appeal.objects.filter(pk=appeal.pk).update(statement=text)
    ctx.conversation.step = EVIDENCE
    return say(ctx, "appeal.ask_evidence")


def _pending(ctx: Context) -> dict[str, dict[str, Any]]:
    return ctx.conversation.state.setdefault("pending", {})


def _evidence(ctx: Context, command: str) -> list[Reply]:
    appeal = _draft(ctx)
    if appeal is None:
        return _lost(ctx)
    msg = ctx.msg
    if msg.kind in MEDIA_KINDS:
        pending = _pending(ctx)
        if msg.message_id in pending:
            return []
        if appeal.evidence.count() + len(pending) >= MAX_ITEMS:
            return say(ctx, "appeal.limit_items")
        pending[msg.message_id] = {"t": time.time(), "kind": msg.kind}
        ctx.enqueue_after(
            "appeals.ingest_media", appeal_id=appeal.pk, message_id=msg.message_id, kind=msg.kind
        )
        return say(ctx, "appeal.file_noted")
    if command not in FINISH_WORDS:
        return say(ctx, "appeal.ask_evidence")
    now = time.time()
    pending = _pending(ctx)
    for message_id, entry in list(pending.items()):
        if now - entry["t"] > PENDING_STALE.total_seconds():
            del pending[message_id]
    if pending:
        return say(ctx, "appeal.still_processing")
    if refusal := service.submit(appeal):
        ctx.conversation.reset()
        return say(ctx, REFUSALS[refusal])
    ctx.conversation.reset()
    return say(ctx, "appeal.submitted")


def register() -> None:
    register_intent("appeal", start)
    register_flow(FLOW, _handle)
