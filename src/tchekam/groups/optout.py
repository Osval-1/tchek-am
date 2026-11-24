"""STOP GROUP: a poster's opt-out from group listening (ADR-012).

Opting out deletes every group sighting of the sender's number, the images only those
sightings kept alive (with their thumbnails), and stops all later collection: their group
images are discarded before download. Opt-out and the group ingest job serialise on a
per-poster lock, so an image being stored while the poster opts out is either deleted by the
opt-out or refused by the job, never kept.
"""

import hashlib

from django.db import connection, transaction

from tchekam.ai.product_photo import forget
from tchekam.conversations.models import BotUser
from tchekam.conversations.router import Context, Reply, register_intent
from tchekam.core.audit import audit
from tchekam.i18n import t
from tchekam.identifiers.phone import normalize_cm_number
from tchekam.imaging.erase import Erased, delete_sightings
from tchekam.imaging.models import ImageSighting

from .models import GroupOptOut

INTENT = "group_opt_out"
_LANGS = ("fr", "en", "pcm")


def poster_key(sender_phone: str | None) -> str | None:
    """The opt-out key for a sender's digits: "+<digits>", like BotUser.wa_phone."""
    return f"+{sender_phone}" if sender_phone else None


def is_opted_out(wa_phone: str) -> bool:
    return GroupOptOut.objects.filter(wa_phone=wa_phone).exists()


def lock_poster(wa_phone: str) -> None:
    """Transaction-scoped Postgres advisory lock for one poster. Call inside atomic()."""
    digest = hashlib.sha256(f"groups.poster:{wa_phone}".encode()).digest()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)", [int.from_bytes(digest[:8], "big", signed=True)]
        )


def opt_out(user: BotUser) -> Erased:
    """Record the opt-out and delete the user's group sightings. Idempotent, transactional."""
    with transaction.atomic():
        lock_poster(user.wa_phone)
        GroupOptOut.objects.get_or_create(wa_phone=user.wa_phone)
        e164 = normalize_cm_number(user.wa_phone)
        sightings = (
            ImageSighting.objects.filter(
                context=ImageSighting.Context.GROUP, phone_number__e164=e164
            )
            if e164
            else ImageSighting.objects.none()
        )
        erased = delete_sightings(sightings)
        # Counts only, never content or the number; the object is the internal user id.
        audit(None, "groups.opt_out", user, sightings=erased.sightings, images=erased.images)
        shas = erased.sha256s
        transaction.on_commit(lambda: forget(shas))
    return erased


def handle_group_opt_out(ctx: Context) -> list[Reply]:
    erased = opt_out(ctx.user)
    key = "groups.opt_out.done" if erased.sightings else "groups.opt_out.nothing"
    if ctx.lang is None:  # STOP GROUP works before onboarding: answer in every language
        return [Reply("\n\n".join(t(key, lang) for lang in _LANGS))]
    return [Reply(t(key, ctx.lang))]


def register() -> None:
    register_intent(INTENT, handle_group_opt_out)
