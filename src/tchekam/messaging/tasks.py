import logging

from django.utils import timezone

from tchekam.conversations.service import handle_private_message
from tchekam.core.tasks import register

from . import hooks
from .channel import InboundMessage, get_channel
from .models import InboundEvent
from .parser import parse_wasender_payload

logger = logging.getLogger(__name__)


def _handle(msg: InboundMessage) -> None:
    if msg.chat_type == "group":
        hooks.on_group_message(msg)
        return
    if not msg.sender_phone:
        return
    channel = get_channel()
    for reply in handle_private_message(msg):
        if reply.image_url:
            channel.send_image(msg.sender_phone, reply.image_url, caption=reply.text)
        else:
            channel.send_text(msg.sender_phone, reply.text)


@register("messaging.process_inbound")
def process_inbound(event_id: int) -> None:
    event = InboundEvent.objects.filter(pk=event_id).first()
    if event is None:
        logger.warning("process_inbound: event %s not found", event_id)
        return
    if event.status != InboundEvent.Status.RECEIVED:
        return

    msg = parse_wasender_payload(event.payload)
    if msg is None:
        event.status = InboundEvent.Status.IGNORED
        event.save(update_fields=["status"])
        return

    try:
        _handle(msg)
    except Exception as exc:
        # Class name only: exception text from providers can echo bodies or numbers.
        event.status = InboundEvent.Status.FAILED
        event.error = type(exc).__name__
        event.save(update_fields=["status", "error"])
        logger.warning("process_inbound: event %s failed with %s", event.pk, event.error)
        return

    event.status = InboundEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "processed_at"])
