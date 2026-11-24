"""Background work for the report flow: media ingestion and evidence extraction.

Both tasks are idempotent and never raise: the reporter is told when something could not be
done. Transcripts, story text, numbers and file names are personal data and are never logged.
"""

import hashlib
import logging
from dataclasses import dataclass, replace
from datetime import date

from django.db import transaction
from django.db.models import Sum

from tchekam.ai.extraction import extract_evidence
from tchekam.ai.schemas import Extraction
from tchekam.conversations.models import BotUser, Conversation
from tchekam.conversations.outbound import send_to_user
from tchekam.core import redact
from tchekam.core.storage import ObjectNotFoundError, get_object_store, new_key
from tchekam.core.tasks import register
from tchekam.i18n import t
from tchekam.identifiers.models import get_or_create_account_name, get_or_create_phone
from tchekam.messaging.channel import ChannelError, MediaTooLarge, get_channel
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.parser import parse_wasender_payload
from tchekam.speech.base import get_speech_to_text

from . import flow, hooks, notify
from .models import Evidence, Report, ReportSubject

logger = logging.getLogger(__name__)

MAX_TOTAL_BYTES = 15 * 1024 * 1024  # across all evidence of one report
LOW_CONFIDENCE = 0.4
# Evidence can be added while drafting and while the moderator waits for more information.
INGEST_STATUSES = (Report.Status.DRAFT, Report.Status.NEEDS_INFO)
EVIDENCE_KINDS = {
    "chat": Evidence.Kind.CHAT,
    "momo_sms": Evidence.Kind.MOMO_SMS,
    "post": Evidence.Kind.POST,
    "other": Evidence.Kind.OTHER,
}
FAILED = "report.file_failed"
ACK = "report.ack"


@dataclass(frozen=True)
class _Stored:
    """A file already put in the object store, waiting to become an Evidence row."""

    key: str
    kind: str
    mimetype: str
    sha256: str
    size: int
    transcript: str = ""
    confidence: float | None = None


def _used_bytes(report_id: int) -> int:
    return Evidence.objects.filter(report_id=report_id).aggregate(s=Sum("size_bytes"))["s"] or 0


def _log(task: str, report_id: int, what: str) -> None:
    logger.warning("%s: report %s: %s", task, redact(report_id), what)


# Ingest ---------------------------------------------------------------------------------------


@register("reports.ingest_media")
def ingest_media(report_id: int, message_id: str, kind: str) -> None:
    """Download one image or voice note, store it, transcribe audio, add it to the report.

    Idempotent per (report, message): a repeated run finds the Evidence and does nothing.
    The stored blob is deleted exactly when no Evidence row was created for it; the reporter
    is messaged only after that decision, and a messaging failure changes nothing.
    """
    try:
        fetched = _fetch(report_id, message_id, kind)
    except Exception as exc:  # untrusted media and providers: anything can fail
        _log("ingest_media", report_id, type(exc).__name__)
        fetched = FAILED
    kept, notice = False, None
    try:
        kept, notice = _settle(report_id, message_id, fetched)
    except Exception as exc:
        _log("ingest_media", report_id, type(exc).__name__)
    if isinstance(fetched, _Stored) and not kept:
        _discard(report_id, fetched.key)  # stored but not kept: leave nothing behind
    if notice is None:
        return
    try:
        user, key = notice
        lang = user.language
        send_to_user(user, text=t(key, lang, items=flow.item_counts_text(report_id, lang)))
    except Exception as exc:
        _log("ingest_media", report_id, f"notify {type(exc).__name__}")


def _discard(report_id: int, key: str) -> None:
    try:
        get_object_store().delete(key)
    except Exception as exc:
        _log("ingest_media", report_id, f"delete {type(exc).__name__}")


def _fetch(report_id: int, message_id: str, kind: str) -> _Stored | str | None:
    """The slow part, outside any lock. Returns the stored file, a copy key, or None (skip)."""
    report = Report.objects.select_related("reporter").filter(pk=report_id).first()
    if report is None or report.reporter is None or report.status not in INGEST_STATUSES:
        return None
    if Evidence.objects.filter(report=report, source_message_id=message_id).exists():
        return None  # a duplicate run
    if Evidence.objects.filter(report=report).count() >= flow.MAX_ITEMS:
        return "report.limit_items"
    event = InboundEvent.objects.filter(message_id=message_id).first()
    msg = parse_wasender_payload(event.payload) if event else None
    if msg is None or msg.kind != kind or kind not in flow.MEDIA_KINDS:
        return FAILED
    if msg.sender_phone != report.reporter.wa_phone.lstrip("+"):
        _log("ingest_media", report_id, "sender mismatch")
        return None
    try:
        data, mimetype = get_channel().download_media(msg)
    except MediaTooLarge:
        return "report.limit_size"
    except ChannelError as exc:
        _log("ingest_media", report_id, f"download {type(exc).__name__}")
        return FAILED
    if not data:
        return FAILED
    if _used_bytes(report_id) + len(data) > MAX_TOTAL_BYTES:
        return "report.limit_size"

    key = get_object_store().put(new_key("evidence"), data, mimetype)
    try:
        stored = _Stored(
            key=key,
            kind=Evidence.Kind.VOICE if kind == "audio" else Evidence.Kind.OTHER,
            mimetype=mimetype,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
        )
        if kind == "audio":
            heard = get_speech_to_text().transcribe(
                data, mimetype or "", language_hint=report.reporter.language
            )
            stored = replace(stored, transcript=heard.text, confidence=heard.confidence)
    except Exception:
        _discard(report_id, key)  # no row can exist yet, so the blob would be orphaned
        raise
    return stored


def _settle(
    report_id: int, message_id: str, fetched: _Stored | str | None
) -> tuple[bool, tuple[BotUser, str] | None]:
    """Under the conversation lock: re-check limits, create the Evidence, clear the pending slot.

    The lock serialises this with the router, so files arriving together cannot overshoot the
    item count or total size. Returns (Evidence row created, (user, copy key) to send or None).
    The reporter is messaged only while collecting for this report, and not during extraction.
    """
    report = Report.objects.select_related("reporter").filter(pk=report_id).first()
    user = report.reporter if report else None
    if user is None:
        return False, None
    outcome = fetched if isinstance(fetched, str) else None
    with transaction.atomic():
        conv = Conversation.objects.select_for_update().filter(user=user).first()
        collecting = (
            conv is not None
            and conv.flow in (flow.COLLECT, flow.NEEDS_INFO)
            and conv.state.get("report_id") == report_id
        )
        if collecting:
            conv.state.get("pending", {}).pop(message_id, None)
            conv.save(update_fields=["state", "updated_at"])
        if isinstance(fetched, _Stored):
            outcome = _keep(report_id, message_id, fetched)
    kept = outcome == ACK
    if not (collecting and outcome) or conv.step == flow.EXTRACTING:
        return kept, None
    return kept, (user, outcome)


def _keep(report_id: int, message_id: str, stored: _Stored) -> str | None:
    row = Report.objects.select_for_update().get(pk=report_id)
    evidence = Evidence.objects.filter(report=row)
    if row.status not in INGEST_STATUSES or evidence.filter(source_message_id=message_id).exists():
        return None
    if evidence.count() >= flow.MAX_ITEMS:
        return "report.limit_items"
    if _used_bytes(report_id) + stored.size > MAX_TOTAL_BYTES:
        return "report.limit_size"
    Evidence.objects.create(
        report=row,
        kind=stored.kind,
        object_key=stored.key,
        mimetype=stored.mimetype[:100],
        sha256=stored.sha256,
        size_bytes=stored.size,
        transcript=stored.transcript,
        transcript_confidence=stored.confidence,
        source_message_id=message_id,
    )
    return ACK


# Extract --------------------------------------------------------------------------------------


@register("reports.extract")
def extract(report_id: int) -> None:
    """Run AI extraction over the report's evidence, persist it, then hand over to the reporter.

    Re-running on unchanged evidence and story does not call the model again (no double bill).
    """
    report = Report.objects.select_related("reporter").filter(pk=report_id).first()
    if report is None or report.reporter is None or report.status != Report.Status.DRAFT:
        return
    # Every failure path ends in analysis_failed (never raises): the reporter goes back to
    # collecting and is told to send DONE again, so EXTRACTING never outlives its job.
    try:
        extraction = _extract(report)
        hooks.after_extraction(report)
        if _needs_details(report, extraction):
            flow.ask_for_details(report)
        else:
            flow.present_for_confirmation(report)
    except Exception as exc:
        _log("extract", report_id, type(exc).__name__)
        flow.analysis_failed(report)


def _inputs_key(evidence: list[Evidence], story: str) -> str:
    """Fingerprint of what extraction reads, so unchanged input is never sent twice."""
    digest = hashlib.sha256()
    for item in evidence:
        digest.update(f"{item.pk}:{item.sha256};".encode())
    digest.update(story.encode())
    return digest.hexdigest()


def _extract(report: Report) -> Extraction:
    evidence = list(report.evidence.order_by("created_at", "pk"))
    key = _inputs_key(evidence, report.story_text)
    previous = report.ai_extraction
    # A failed run is not reused: the next DONE retries the model.
    if previous.get("inputs_key") == key and not previous.get("extraction_failed"):
        return Extraction.model_validate({k: v for k, v in previous.items() if k != "inputs_key"})

    store = get_object_store()
    images: list[Evidence] = []
    blobs: list[tuple[bytes, str]] = []
    for item in evidence:
        if item.kind == Evidence.Kind.VOICE:
            continue
        try:
            blobs.append((store.get(item.object_key), item.mimetype))
        except ObjectNotFoundError:
            _log("extract", report.pk, "evidence object missing")
            continue
        images.append(item)
    transcript = "\n".join(
        e.transcript for e in evidence if e.kind == Evidence.Kind.VOICE and e.transcript
    )
    lang = report.reporter.language or "fr"
    extraction = extract_evidence(
        images=blobs, transcript=transcript or None, story=report.story_text or None, lang=lang
    )
    _persist(report, images, extraction, key)
    return extraction


def _valid_amounts(values: list) -> list[int]:
    return [a for a in values if isinstance(a, int) and 0 < a <= flow.MAX_AMOUNT]


def _first_date(values: list[str]) -> date | None:
    for value in values:
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            continue
    return None


def _persist(report: Report, images: list[Evidence], extraction: Extraction, key: str) -> None:
    lang = report.reporter.language
    summary = extraction.summary.strip()
    if extraction.summary_filtered or not summary:
        summary = t("report.summary_neutral", lang)
    amounts = _valid_amounts(extraction.amounts_xaf)
    previous_ai = _valid_amounts(report.ai_extraction.get("amounts_xaf", []))
    # An amount that differs from the earlier AI value was typed by the reporter: keep it.
    ai_owned = report.amount_xaf is None or report.amount_xaf == (previous_ai or [None])[0]
    with transaction.atomic():
        # Tamper observations are stored only here, in ai_extraction["tamper_observations"]
        # (report-level; the model does not tie them to an image). Issue 13 reads them from
        # there; Evidence.tamper_flags stays empty.
        report.ai_extraction = {**extraction.model_dump(mode="json"), "inputs_key": key}
        report.summary_ai = summary
        report.scam_type = "" if extraction.extraction_failed else extraction.scam_type
        if amounts and ai_owned:
            report.amount_xaf = amounts[0]
        report.incident_date = _first_date(extraction.dates) or report.incident_date
        report.save(
            update_fields=[
                "ai_extraction",
                "summary_ai",
                "scam_type",
                "amount_xaf",
                "incident_date",
            ]
        )
        for item, kind in zip(images, extraction.evidence_kinds, strict=False):
            item.kind = EVIDENCE_KINDS.get(kind, Evidence.Kind.OTHER)
            item.ai_extraction = {"kind": kind}
            item.save(update_fields=["kind", "ai_extraction"])
        # A re-run on new evidence replaces the earlier AI guesses; user and moderator rows stay.
        report.subjects.filter(source=ReportSubject.Source.AI, confirmed=False).delete()
        for raw in extraction.phone_numbers:
            if phone := get_or_create_phone(raw):
                ReportSubject.objects.get_or_create(
                    report=report,
                    phone_number=phone,
                    role=ReportSubject.Role.SELLER,
                    source=ReportSubject.Source.AI,
                    defaults={"confirmed": False},
                )
        for item in extraction.account_names:
            if account := get_or_create_account_name(item.name, item.provider):
                ReportSubject.objects.get_or_create(
                    report=report,
                    account_name=account,
                    role=ReportSubject.Role.PAYEE,
                    source=ReportSubject.Source.AI,
                    defaults={"confirmed": False},
                )


def _needs_details(report: Report, extraction: Extraction) -> bool:
    """Ask the reporter to type the number and amount when the evidence was unclear."""
    typed = report.subjects.filter(
        source=ReportSubject.Source.USER, role=ReportSubject.Role.SELLER
    ).exists()
    if typed:  # already asked on an earlier pass
        return False
    unclear_voice = report.evidence.filter(
        kind=Evidence.Kind.VOICE, transcript_confidence__lt=LOW_CONFIDENCE
    ).exists()
    nothing_found = not extraction.phone_numbers and not extraction.amounts_xaf
    return extraction.extraction_failed or unclear_voice or nothing_found


# Link ------------------------------------------------------------------------------------------


@register("reports.link")
def link(report_id: int) -> None:
    """Find related reports (same number, name, image or text) once a report is submitted.

    A no-op until Issue 16; queued from the submit step so that issue only fills this in.
    """


# Notify ------------------------------------------------------------------------------------------


# Issue 15 must keep this signature: moderation enqueues it as (report_id=, decision_id=).
@register("notify.report_decided")
def report_decided(report_id: int, decision_id: int) -> None:
    """Tell the reporter about a moderation decision (approved, rejected, needs info, merged).

    Queued after every moderation decision commits. Idempotent; see `notify.notify_decision`.
    """
    notify.notify_decision(report_id, decision_id)
