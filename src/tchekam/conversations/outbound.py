"""Messages sent outside a reply, e.g. from background tasks. Never raises into the caller."""

import logging

from tchekam.messaging.channel import ChannelError, get_channel

from .models import BotUser

logger = logging.getLogger(__name__)


def send_to_user(user: BotUser, text: str | None = None, image_url: str | None = None) -> None:
    """Send a text (or an image with `text` as caption) to a user. Blocked users get nothing."""
    if user.blocked:
        return
    to = user.wa_phone.lstrip("+")  # stored as +E.164; channels take digits
    channel = get_channel()
    try:
        if image_url:
            channel.send_image(to, image_url, caption=text)
        elif text:
            channel.send_text(to, text)
    except ChannelError as exc:
        # Class name only: provider errors can echo bodies or numbers.
        logger.warning("send_to_user: %s for %s", type(exc).__name__, user)
