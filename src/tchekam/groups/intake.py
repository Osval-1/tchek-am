"""Group-message intake (F8, ADR-012). Plugged into messaging as the group-message hook.

`handle_group_message` runs in the messaging.process_inbound job (never in the webhook, never
under a Conversation lock) and only makes cheap decisions:

- no PartnerGroup for the jid: leave the group, at most once per jid, and store nothing;
- a PAUSED or LEFT group: ignore (no leave: the record says consent exists or existed);
- an ACTIVE group: an image from a known, Cameroonian, not-opted-out poster is queued for
  `groups.ingest_image`; anything else (text, audio, video, stickers, contacts, documents)
  is ignored and never stored.

The job downloads the image, asks the product classifier, and stores a sighting only for a
product photo. The bot never sends anything to a group (MessagingChannel refuses it).
"""

import logging

from django.db import IntegrityError, transaction

from tchekam.ai.product_photo import is_product_photo
from tchekam.core.tasks import enqueue
from tchekam.core.tasks import register as register_task
from tchekam.identifiers.models import get_or_create_phone
from tchekam.identifiers.phone import normalize_cm_number
from tchekam.imaging.hashing import ImageRejected
from tchekam.imaging.ingest import SightingContext, ingest
from tchekam.imaging.models import Image, ImageSighting
from tchekam.messaging import hooks
from tchekam.messaging.channel import ChannelError, InboundMessage, get_channel
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.parser import parse_wasender_payload

from .models import PartnerGroup, UnconsentedGroupLeave
from .optout import is_opted_out, lock_poster, poster_key

logger = logging.getLogger(__name__)

TASK = "groups.ingest_image"


def _poster(msg: InboundMessage) -> tuple[str, str] | None:
    """(opt-out key, E.164) of the poster, or None when no Cameroonian number is known.

    A LID-only sender has no number; a foreign number cannot become a PhoneNumber. Both are
    discarded: a sighting is only useful (and only allowed) with the poster's number.
    """
    key = poster_key(msg.sender_phone)
    e164 = normalize_cm_number(key) if key else None
    return (key, e164) if key and e164 else None


def _leave_once(group_jid: str) -> None:
    # The unique jid row is the claim. A concurrent delivery blocks on it until this
    # transaction ends, then finds it and does not leave again. If the leave call fails, the
    # claim rolls back with it, so a later message retries.
    with transaction.atomic():
        _, created = UnconsentedGroupLeave.objects.get_or_create(group_jid=group_jid)
        if created:
            get_channel().leave_group(group_jid)


def handle_group_message(msg: InboundMessage) -> None:
    if not msg.group_jid:
        return
    group = PartnerGroup.objects.filter(group_jid=msg.group_jid).first()
    if group is None:
        _leave_once(msg.group_jid)
        return
    if group.status != PartnerGroup.Status.ACTIVE or msg.kind != "image":
        return
    poster = _poster(msg)
    if poster is None or is_opted_out(poster[0]):
        return  # decided before any download
    message_id = msg.message_id
    transaction.on_commit(lambda: enqueue(TASK, message_id=message_id))


def _group_image(message_id: str) -> tuple[InboundMessage, str, str] | None:
    event = InboundEvent.objects.filter(message_id=message_id).first()
    msg = parse_wasender_payload(event.payload) if event else None
    if msg is None or msg.chat_type != "group" or msg.kind != "image":
        return None
    poster = _poster(msg)
    if poster is None or is_opted_out(poster[0]):
        return None
    if not PartnerGroup.objects.filter(
        group_jid=msg.group_jid, status=PartnerGroup.Status.ACTIVE
    ).exists():
        return None
    return msg, *poster


def _store(data: bytes, group_jid: str, wa_phone: str, e164: str) -> None:
    """Ingest under the poster lock, re-checking consent and opt-out at the last moment."""
    for attempt in range(2):
        try:
            with transaction.atomic():
                lock_poster(wa_phone)
                group = PartnerGroup.objects.filter(
                    group_jid=group_jid, status=PartnerGroup.Status.ACTIVE
                ).first()
                if group is None or is_opted_out(wa_phone):
                    return
                ctx = SightingContext(
                    context=ImageSighting.Context.GROUP,
                    phone_number=get_or_create_phone(e164),
                    group=group,
                )
                ingest(data, Image.Source.GROUP, ctx)
            return
        except IntegrityError:
            # A concurrent opt-out deleted the image this sighting pointed at; store afresh.
            if attempt:
                raise


@register_task(TASK)
def ingest_group_image(message_id: str) -> None:
    """Download, classify, and keep only product photos. Never raises; logs class names only."""
    try:
        found = _group_image(message_id)
        if found is None:
            return
        msg, wa_phone, e164 = found
        try:
            data, _ = get_channel().download_media(msg)
        except ChannelError as exc:  # includes MediaTooLarge
            logger.warning("groups.ingest_image: download %s", type(exc).__name__)
            return
        if not data or is_product_photo(data) is not True:
            return  # not a product (or could not tell): the bytes are dropped here
        _store(data, msg.group_jid, wa_phone, e164)
    except ImageRejected:
        return
    except Exception as exc:  # untrusted bytes and external services: anything can fail
        logger.warning("groups.ingest_image: %s", type(exc).__name__)


def register() -> None:
    hooks.register_group_handler(handle_group_message)
