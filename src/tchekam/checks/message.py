"""Message check (F3): which common red flags does a pasted message show?

The router handler only checks the quota and queues `checks.message`; the LLM call runs in that
task, outside the Conversation lock (ADR-017), and the answer goes out through `send_to_user`.
The reply lists flags and never gives a verdict. Flag text always comes from the catalogue, also
for flags the LLM found: the model's own wording is never shown, so all copy stays reviewed.
"""

import hashlib
import hmac
import logging

from django.conf import settings
from django.db import transaction

from tchekam.ai.message_flags import llm_flag_codes
from tchekam.conversations.models import BotUser
from tchekam.conversations.outbound import send_to_user
from tchekam.conversations.router import Context, Reply, register_intent, say
from tchekam.core import redact
from tchekam.core.tasks import register as register_task
from tchekam.i18n import t
from tchekam.identifiers.phone import find_numbers
from tchekam.messaging.models import InboundEvent
from tchekam.messaging.parser import parse_wasender_payload

from .limits import check_allowed
from .models import CheckLog
from .number import band_summary
from .redflags import FLAG_CODES, MAX_CHARS, normalise, rule_flags

logger = logging.getLogger(__name__)

MAX_FLAGS = 5
MAX_NUMBERS = 2


def merge_flags(rule_codes: list[str], llm_codes: list[str] | None) -> list[str]:
    """Rule flags first, then the model's, without duplicates, at most MAX_FLAGS."""
    merged = dict.fromkeys(c for c in [*rule_codes, *(llm_codes or [])] if c in FLAG_CODES)
    return list(merged)[:MAX_FLAGS]


def _number_lines(text: str, lang: str | None) -> list[str]:
    numbers = find_numbers(text[:MAX_CHARS])[:MAX_NUMBERS]
    if not numbers:
        return []
    # Embedded numbers deliberately do not bump PhoneNumber.check_count: that counter ranks
    # numbers for moderation by how often people look them up directly, and a number merely
    # mentioned in a pasted text is a weaker signal of interest.
    lines = [t("check.message.numbers_header", lang)]
    for e164 in numbers:
        try:
            lines.append(band_summary(e164, lang))
        except Exception as exc:  # a failed lookup must not sink the message reply
            logger.warning("checks.message: band lookup %s", type(exc).__name__)
            lines.append(f"{e164}\n{t('check.message.number_unavailable', lang)}")
    return lines


def build_reply(text: str, flags: list[str], lang: str | None) -> str:
    if flags:
        lines = [t("check.message.flags_header", lang)]
        lines += [f"- {t(f'check.message.flag.{code}', lang)}" for code in flags]
    else:
        lines = [t("check.message.none", lang)]
    parts = ["\n".join(lines)]
    if numbers := _number_lines(text, lang):
        parts.append("\n".join(numbers))
    parts.append(t("check.message.caution", lang))
    return "\n\n".join(parts)


def _fingerprint(text: str) -> str:
    """Keyed hash of the normalised text: repeats can be counted, the text cannot be read back."""
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, normalise(text).encode(), hashlib.sha256).hexdigest()


def _log_if_allowed(user: BotUser, text: str) -> bool:
    """Quota check and log write under one row lock, so parallel messages cannot overshoot."""
    with transaction.atomic():
        BotUser.objects.select_for_update().get(pk=user.pk)
        if not check_allowed(user):
            return False
        # The raw text is never stored; a flag list is not a band, so the band stays "none".
        CheckLog.objects.create(
            user=user,
            kind=CheckLog.Kind.MESSAGE,
            subject_ref=_fingerprint(text),
            result_band=CheckLog.Band.NONE,
        )
    return True


def _load_text(user: BotUser, message_id: str) -> str | None:
    # The text is re-read from the stored inbound event instead of travelling through the job
    # queue, so the queue table never holds message content.
    event = InboundEvent.objects.filter(message_id=message_id).first()
    msg = parse_wasender_payload(event.payload) if event else None
    if msg is None or msg.kind != "text" or msg.sender_phone != user.wa_phone.lstrip("+"):
        return None  # unknown message, or one this user did not send
    return msg.text or None


def _llm_codes(text: str) -> list[str] | None:
    try:
        return llm_flag_codes(text, FLAG_CODES)
    except Exception as exc:  # the rules alone are a good enough answer
        logger.warning("checks.message: llm %s", type(exc).__name__)
        return None


def _run(user: BotUser, message_id: str) -> None:
    lang = user.language
    text = _load_text(user, message_id)
    if text is None:
        send_to_user(user, text=t("check.message.failed", lang))
        return
    flags = merge_flags(rule_flags(text), _llm_codes(text))
    reply = build_reply(text, flags, lang)
    if not _log_if_allowed(user, text):
        send_to_user(user, text=t("check.limit_reached", lang))
        return
    send_to_user(user, text=reply)


@register_task("checks.message")
def check_message(user_id: int, message_id: str) -> None:
    """Never raises: the user always hears back, and a retry would be a second logged check."""
    user = BotUser.objects.filter(pk=user_id).first()
    if user is None:
        return
    try:
        _run(user, message_id)
    except Exception as exc:  # message text must stay out of logs: class name only
        logger.warning("checks.message: user %s: %s", redact(user_id), type(exc).__name__)
        send_to_user(user, text=t("check.message.failed", user.language))


def handle_check_message(ctx: Context) -> list[Reply]:
    if not ctx.msg.text or not ctx.msg.message_id:
        return say(ctx, "check.message.failed")
    if not check_allowed(ctx.user):  # refuse early; the task re-checks under lock before logging
        return say(ctx, "check.limit_reached")
    ctx.enqueue_after("checks.message", user_id=ctx.user.pk, message_id=ctx.msg.message_id)
    return say(ctx, "check.message.checking")


def register() -> None:
    register_intent("check_message", handle_check_message)
