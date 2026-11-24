"""Builders for retention tests. Every rule takes an explicit `now`, so no clock is frozen."""

from datetime import datetime, timedelta
from itertools import count
from zoneinfo import ZoneInfo

from tchekam.appeals.models import Appeal, AppealEvidence
from tchekam.checks.models import CheckLog
from tchekam.conversations.models import BotUser
from tchekam.core.storage import get_object_store
from tchekam.identifiers.models import PhoneNumber
from tchekam.imaging.models import Image, ImageSighting
from tchekam.messaging.models import InboundEvent
from tchekam.reports.models import Evidence, Report, ReportSubject

DOUALA = ZoneInfo("Africa/Douala")
NOW = datetime(2026, 11, 24, 2, 0, tzinfo=DOUALA)
MINUTE = timedelta(minutes=1)
_n = count(1)


def user(**kw) -> BotUser:
    kw.setdefault("wa_phone", f"+2376700{next(_n):05d}")
    kw.setdefault("language", "en")
    return BotUser.objects.create(**kw)


def phone(e164: str | None = None, **kw) -> PhoneNumber:
    return PhoneNumber.objects.create(e164=e164 or f"+2376900{next(_n):05d}", operator="mtn", **kw)


def report(status="draft", reporter=None, *, seller=None, **kw) -> Report:
    """A report with full personal data, one seller subject and one evidence file."""
    reporter = reporter or user()
    defaults = {
        "story_text": "I paid and nothing came",
        "ai_extraction": {"summary": "secret"},
        "summary_ai": "AI summary",
        "summary_final": "Final summary",
        "amount_xaf": 25000,
    }
    r = Report.objects.create(reporter=reporter, status=status, **{**defaults, **kw})
    ReportSubject.objects.create(
        report=r,
        phone_number=seller or phone(),
        role=ReportSubject.Role.SELLER,
        source=ReportSubject.Source.MODERATOR,
        confirmed=True,
    )
    evidence(r)
    return r


def evidence(r: Report, kind=Evidence.Kind.CHAT, sha256=None, **kw) -> Evidence:
    n = next(_n)
    key = get_object_store().put(f"evidence/test-{n}", b"blob", "image/png")
    return Evidence.objects.create(
        report=r,
        kind=kind,
        object_key=key,
        mimetype="audio/ogg" if kind == Evidence.Kind.VOICE else "image/png",
        sha256=sha256 or f"{n:064d}",
        size_bytes=4,
        transcript="what the reporter said" if kind == Evidence.Kind.VOICE else "",
        tamper_flags=["edited"],
        **kw,
    )


def set_time(model, pk, **fields):
    """Back-date auto_now_add fields (create() ignores them)."""
    model.objects.filter(pk=pk).update(**fields)


def event(received_at, *, sender="237670000001", group=False, **kw) -> InboundEvent:
    mid = f"EV-{next(_n)}"
    if group:
        payload = {
            "event": "messages-group.received",
            "data": {
                "messages": {
                    "key": {
                        "id": mid,
                        "fromMe": False,
                        "remoteJid": "120363000000000001@g.us",
                        "participant": f"{sender}@s.whatsapp.net",
                        "cleanedParticipantPn": sender,
                    },
                    "message": {"imageMessage": {"url": "https://media", "mediaKey": "k"}},
                    "redacted": "image",
                    "messageTimestamp": 1,
                }
            },
        }
    else:
        payload = {
            "event": "messages.received",
            "data": {
                "messages": {
                    "key": {
                        "id": mid,
                        "remoteJid": f"{sender}@s.whatsapp.net",
                        "cleanedSenderPn": sender,
                    },
                    "message": {"conversation": "hello"},
                }
            },
        }
    kw.setdefault("status", InboundEvent.Status.PROCESSED)
    e = InboundEvent.objects.create(message_id=mid, event=payload["event"], payload=payload, **kw)
    set_time(InboundEvent, e.pk, received_at=received_at)
    return e


def check_log(created_at, subject_ref="+237690000001", kind="number", user=None) -> CheckLog:
    log = CheckLog.objects.create(
        user=user, kind=kind, subject_ref=subject_ref, result_band="green"
    )
    set_time(CheckLog, log.pk, created_at=created_at)
    return log


def group_sighting(seen_at, poster=None, *, image=None) -> ImageSighting:
    n = next(_n)
    if image is None:
        thumb = get_object_store().put(f"thumbnails/test-{n}", b"jpeg", "image/jpeg")
        image = Image.objects.create(sha256=f"{n:064x}", thumbnail_key=thumb, source="group")
    return ImageSighting.objects.create(
        image=image,
        phone_number=poster or phone(),
        context=ImageSighting.Context.GROUP,
        seen_at=seen_at,
    )


def appeal(status="draft", appellant=None, number=None, **kw) -> Appeal:
    a = Appeal.objects.create(
        phone_number=number or phone(),
        appellant=appellant or user(),
        kind=Appeal.Kind.WRONG,
        statement="These reports are about someone else",
        status=status,
        **kw,
    )
    appeal_evidence(a)
    return a


def appeal_evidence(a: Appeal) -> AppealEvidence:
    n = next(_n)
    key = get_object_store().put(f"appeal-evidence/test-{n}", b"blob", "image/png")
    return AppealEvidence.objects.create(
        appeal=a,
        object_key=key,
        mimetype="image/png",
        sha256=f"{n:064d}",
        size_bytes=4,
        source_message_id=f"AP-{n}",
    )
