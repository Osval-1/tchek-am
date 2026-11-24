"""Background work for appeals: evidence ingestion, decision messages, draft clean-up.

Tasks are idempotent and never raise into the worker for expected failures. Files, statements
and numbers are personal data and are never logged.
"""

import hashlib
import logging

from django.db import transaction
from django.db.models import Sum

from tchekam.conversations.models import Conversation
from tchekam.conversations.outbound import send_to_user
from tchekam.core import redact
from tchekam.core.storage import get_object_store, new_key
from tchekam.core.tasks import register
from tchekam.i18n import t
from tchekam.messaging.channel import ChannelError, MediaTooLarge, get_channel
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.parser import parse_wasender_payload

from . import notify
from .models import Appeal, AppealEvidence

logger = logging.getLogger(__name__)

MAX_ITEMS = 5
MAX_TOTAL_BYTES = 10 * 1024 * 1024
FLOW = "appeal"
FAILED, LIMIT, OK = "appeal.file_failed", "appeal.limit_items", None


def _log(appeal_id: int, what: str) -> None:
    logger.warning("appeals.ingest_media: appeal %s: %s", redact(appeal_id), what)


def _used(appeal_id: int) -> int:
    rows = AppealEvidence.objects.filter(appeal_id=appeal_id)
    return rows.aggregate(s=Sum("size_bytes"))["s"] or 0


@register("appeals.ingest_media")
def ingest_media(appeal_id: int, message_id: str, kind: str) -> None:
    """Download one image or voice note into the draft; tell the user only if it failed."""
    outcome, key = FAILED, None
    try:
        outcome, key, data_info = _fetch(appeal_id, message_id, kind)
    except Exception as exc:  # untrusted media and providers: anything can fail
        _log(appeal_id, type(exc).__name__)
        data_info = None
    kept = False
    try:
        if data_info is not None:
            outcome, kept = _settle(appeal_id, message_id, key, data_info)
        else:
            _clear_pending(appeal_id, message_id)
    except Exception as exc:
        _log(appeal_id, type(exc).__name__)
        outcome = FAILED
    if key and not kept:
        try:
            get_object_store().delete(key)  # stored but not kept: leave nothing behind
        except Exception as exc:
            _log(appeal_id, f"delete {type(exc).__name__}")
    if outcome:
        _tell(appeal_id, outcome)


def _fetch(appeal_id: int, message_id: str, kind: str):
    """The slow part, outside any lock: (failure copy key, blob key, (mime, sha256, size))."""
    appeal = Appeal.objects.select_related("appellant").filter(pk=appeal_id).first()
    if appeal is None or appeal.appellant is None or appeal.status != Appeal.Status.DRAFT:
        return None, None, None
    event = InboundEvent.objects.filter(message_id=message_id).first()
    msg = parse_wasender_payload(event.payload) if event else None
    if msg is None or msg.kind != kind:
        return FAILED, None, None
    if msg.sender_phone != appeal.appellant.wa_phone.lstrip("+"):
        return None, None, None  # not this user's message: ignore silently
    try:
        data, mimetype = get_channel().download_media(msg)
    except MediaTooLarge:
        return "appeal.limit_size", None, None
    except ChannelError as exc:
        _log(appeal_id, f"download {type(exc).__name__}")
        return FAILED, None, None
    if not data:
        return FAILED, None, None
    if _used(appeal_id) + len(data) > MAX_TOTAL_BYTES:
        return "appeal.limit_size", None, None
    key = get_object_store().put(new_key("appeal-evidence"), data, mimetype)
    return None, key, (mimetype, hashlib.sha256(data).hexdigest(), len(data))


def _clear_pending(appeal_id: int, message_id: str) -> None:
    with transaction.atomic():
        conv = _conversation_for(appeal_id)
        if conv is not None:
            conv.state.get("pending", {}).pop(message_id, None)
            conv.save(update_fields=["state", "updated_at"])


def _conversation_for(appeal_id: int) -> Conversation | None:
    conv = (
        Conversation.objects.select_for_update()
        .filter(flow=FLOW, state__appeal_id=appeal_id)
        .first()
    )
    return conv


def _settle(appeal_id: int, message_id: str, key: str | None, info) -> tuple[str | None, bool]:
    """Under the conversation lock, so files arriving together cannot overshoot the limits."""
    mimetype, sha256, size = info
    with transaction.atomic():
        conv = _conversation_for(appeal_id)
        if conv is not None:
            conv.state.get("pending", {}).pop(message_id, None)
            conv.save(update_fields=["state", "updated_at"])
        appeal = Appeal.objects.select_for_update().get(pk=appeal_id)
        rows = AppealEvidence.objects.filter(appeal=appeal)
        if (
            appeal.status != Appeal.Status.DRAFT
            or rows.filter(source_message_id=message_id).exists()
        ):
            return None, False
        if rows.count() >= MAX_ITEMS:
            return LIMIT, False
        if _used(appeal_id) + size > MAX_TOTAL_BYTES:
            return "appeal.limit_size", False
        AppealEvidence.objects.create(
            appeal=appeal,
            object_key=key,
            mimetype=mimetype[:100],
            sha256=sha256,
            size_bytes=size,
            source_message_id=message_id,
        )
    return None, True


def _tell(appeal_id: int, key: str) -> None:
    try:
        appeal = Appeal.objects.select_related("appellant").get(pk=appeal_id)
        if appeal.appellant is not None and appeal.status == Appeal.Status.DRAFT:
            send_to_user(appeal.appellant, text=t(key, appeal.appellant.language))
    except Exception as exc:
        _log(appeal_id, f"notify {type(exc).__name__}")


@register("appeals.notify_decided")
def notify_decided(appeal_id: int) -> None:
    notify.notify_decision(appeal_id)


@register("appeals.discard_draft")
def discard_draft(appeal_id: int) -> None:
    """Delete an abandoned draft and its stored files (queued so S3 calls never hold a lock)."""
    draft = Appeal.objects.filter(pk=appeal_id, status=Appeal.Status.DRAFT).first()
    if draft is None:
        return
    keys = list(draft.evidence.values_list("object_key", flat=True))
    draft.delete()
    store = get_object_store()
    for key in keys:
        try:
            store.delete(key)
        except Exception as exc:
            _log(appeal_id, f"delete {type(exc).__name__}")
