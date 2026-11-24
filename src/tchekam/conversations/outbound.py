"""Messages sent outside a reply, e.g. from background tasks. Never raises into the caller."""

import logging

from tchekam.messaging import outbox
from tchekam.messaging.channel import ChannelError, get_channel, is_group_jid

from .models import BotUser

logger = logging.getLogger(__name__)


def send_to_user(
    user: BotUser, text: str | None = None, image_url: str | None = None, *, defer: bool = True
) -> bool:
    """Send a text (or an image with `text` as caption) to a user. Blocked users get nothing.

    Returns whether the message was accepted (errors never raise). With `defer` (the default) the
    send is queued on the `whatsapp` queue, where rate limits and transient failures re-queue it,
    so job results are delayed, not lost; True then only means "queued".
    `defer=False` sends once and reports failure, for callers that keep their own fallback
    (reply-window notifications queue a PendingNotification).
    """
    if user.blocked:
        return False
    to = user.wa_phone.lstrip("+")  # stored as +E.164; channels take digits
    if is_group_jid(to):  # the bot never writes to a group (ADR-012); cannot happen via BotUser
        logger.warning("send_to_user: refused group target for %s", user)
        return False
    if not (text or image_url):
        return False
    if defer:
        # Queued, not sent here: background jobs run on the default queue, and every send must
        # go through the `whatsapp` queue's locks (at most 3 at once, ordered per recipient).
        outbox.schedule(to, [{"text": text, "image_url": image_url}], delay=0)
        return True
    channel = get_channel()
    try:
        if image_url:
            channel.send_image(to, image_url, caption=text)
        else:
            channel.send_text(to, text or "")
    except ChannelError as exc:
        # Class name only: provider errors can echo bodies or numbers.
        logger.warning("send_to_user: %s for %s", type(exc).__name__, user)
        return False
    return True
