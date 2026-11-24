"""Photo check (F2), internal matching: has this product photo been posted by known numbers?

The router handler only checks the quota and queues `checks.photo`; the download, hashing and
search run in that task, outside the Conversation lock (ADR-017), and the answer goes out through
`send_to_user`. The reply is built from counts and a month only: never a number, a group name, or
a judgement of the seller.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.conversations.outbound import send_to_user
from tchekam.conversations.router import Context, Reply, register_intent, say
from tchekam.core import redact
from tchekam.core.tasks import enqueue
from tchekam.core.tasks import register as register_task
from tchekam.i18n import month_year, t
from tchekam.imaging.hashing import ImageRejected
from tchekam.imaging.ingest import SightingContext, ingest
from tchekam.imaging.models import Image, ImageSighting
from tchekam.imaging.search import Match, find_similar
from tchekam.messaging.channel import ChannelError, get_channel
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.parser import parse_wasender_payload

from .limits import check_allowed
from .models import CheckLog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhotoResult:
    number_count: int
    first_seen: datetime | None  # None when nothing relevant matched
    flagged: bool

    @property
    def matched(self) -> bool:
        return self.first_seen is not None


def summarise(image: Image, matches: list[Match]) -> PhotoResult:
    """Reduce matches to what the user may be told: how many numbers, since when, any flagged."""
    # The image itself always matches (our own fresh sighting). It only counts when earlier
    # sightings tied it to phone numbers; other images count even without numbers.
    relevant = [m for m in matches if m.image_id != image.pk or m.phone_numbers]
    if not relevant:
        return PhotoResult(0, None, False)
    numbers = {n for m in relevant for n in m.phone_numbers}
    return PhotoResult(
        number_count=len(numbers),
        first_seen=min(m.first_seen for m in relevant),
        flagged=any(m.has_flagged_number for m in relevant),
    )


def _reply_text(result: PhotoResult, lang: str | None) -> str:
    if not result.matched:
        return "\n".join([t("check.photo.no_match", lang), t("check.photo.tips", lang)])
    # The month is the Cameroonian one: a UTC timestamp can fall in the neighbouring month.
    when = month_year(timezone.localtime(result.first_seen), lang)
    if result.number_count == 0:
        lines = [t("check.photo.seen_no_number", lang, when=when)]
    else:
        key = "check.photo.match_one" if result.number_count == 1 else "check.photo.match"
        lines = [t(key, lang, n=result.number_count, when=when)]
    if result.flagged:
        lines.append(t("check.photo.flagged", lang))
    lines.append(t("check.photo.tips", lang))
    return "\n".join(lines)


def after_first_reply(user: BotUser, image: Image) -> None:
    """Queue the web reverse-image search once the internal reply is sent. Never raises.

    The caller's catch-all answers "could not process this photo", which would be false here:
    the user already has their answer and the web check is a bonus.
    """
    try:
        enqueue("imaging.web_check", image_id=image.pk, user_id=user.pk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("checks.photo: web check not queued: %s", type(exc).__name__)


def _download(user: BotUser, message_id: str) -> bytes | None:
    event = InboundEvent.objects.filter(message_id=message_id).first()
    msg = parse_wasender_payload(event.payload) if event else None
    if msg is None or msg.kind != "image" or msg.sender_phone != user.wa_phone.lstrip("+"):
        return None  # unknown message, or one this user did not send
    try:
        data, _ = get_channel().download_media(msg)
    except ChannelError as exc:  # includes MediaTooLarge
        logger.warning("checks.photo: user %s: download %s", redact(user.pk), type(exc).__name__)
        return None
    return data or None


def _log_if_allowed(user: BotUser, image: Image, result: PhotoResult) -> bool:
    """Quota check and log write under one row lock, so parallel photos cannot overshoot."""
    with transaction.atomic():
        BotUser.objects.select_for_update().get(pk=user.pk)
        if not check_allowed(user):
            return False
        # "Flagged" only says orange-or-red; the log keeps the lower bound.
        band = CheckLog.Band.ORANGE if result.flagged else CheckLog.Band.NONE
        CheckLog.objects.create(
            user=user, kind=CheckLog.Kind.IMAGE, subject_ref=image.sha256, result_band=band
        )
    return True


def _run(user: BotUser, message_id: str) -> None:
    lang = user.language
    data = _download(user, message_id)
    if data is None:
        send_to_user(user, text=t("check.photo.failed", lang))
        return
    try:
        image = ingest(
            data,
            Image.Source.SUBMISSION,
            SightingContext(context=ImageSighting.Context.SUBMISSION, bot_user=user),
        )
    except ImageRejected:
        send_to_user(user, text=t("check.photo.rejected", lang))
        return
    result = summarise(image, find_similar(image))
    if not _log_if_allowed(user, image, result):
        send_to_user(user, text=t("check.limit_reached", lang))
        return
    send_to_user(user, text=_reply_text(result, lang))
    after_first_reply(user, image)


@register_task("checks.photo")
def check_photo(user_id: int, message_id: str) -> None:
    """Never raises: the user always hears back, and a retry would double the sighting."""
    user = BotUser.objects.filter(pk=user_id).first()
    if user is None:
        return
    try:
        _run(user, message_id)
    except Exception as exc:  # untrusted bytes and external services: anything can fail
        logger.warning("checks.photo: user %s: %s", redact(user_id), type(exc).__name__)
        send_to_user(user, text=t("check.photo.failed", user.language))


def handle_check_photo(ctx: Context) -> list[Reply]:
    message_id = ctx.extra.get("image_msg_id")
    if not message_id:
        return say(ctx, "check.photo.failed")
    if not check_allowed(ctx.user):  # refuse early; the task re-checks under lock before logging
        return say(ctx, "check.limit_reached")
    ctx.enqueue_after("checks.photo", user_id=ctx.user.pk, message_id=message_id)
    return say(ctx, "check.photo.checking")


def register() -> None:
    register_intent("check_photo", handle_check_photo)
