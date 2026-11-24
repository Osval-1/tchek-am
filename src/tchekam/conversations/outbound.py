"""Messages sent outside a reply, e.g. from background tasks. Never raises into the caller."""

import logging

from tchekam.messaging.channel import ChannelError, get_channel, is_group_jid

from .models import BotUser

logger = logging.getLogger(__name__)


def send_to_user(user: BotUser, text: str | None = None, image_url: str | None = None) -> bool:
    """Send a text (or an image with `text` as caption) to a user. Blocked users get nothing.

    Returns whether the channel accepted it, so callers can queue instead (errors never raise).
    """
    if user.blocked:
        return False
    to = user.wa_phone.lstrip("+")  # stored as +E.164; channels take digits
    if is_group_jid(to):  # the bot never writes to a group (ADR-012); cannot happen via BotUser
        logger.warning("send_to_user: refused group target for %s", user)
        return False
    channel = get_channel()
    try:
        if image_url:
            channel.send_image(to, image_url, caption=text)
        elif text:
            channel.send_text(to, text)
        else:
            return False
    except ChannelError as exc:
        # Class name only: provider errors can echo bodies or numbers.
        logger.warning("send_to_user: %s for %s", type(exc).__name__, user)
        return False
    return True
