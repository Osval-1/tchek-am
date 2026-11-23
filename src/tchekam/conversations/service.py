from django.db import transaction
from django.utils import timezone

from tchekam.messaging.channel import InboundMessage

from .models import BotUser, Conversation
from .router import Context, Reply, route


def handle_private_message(msg: InboundMessage) -> list[Reply]:
    """Load (or create) the sender's user and conversation, then route the message."""
    if not msg.sender_phone:
        return []
    with transaction.atomic():
        user, _ = BotUser.objects.get_or_create(wa_phone=f"+{msg.sender_phone}")
        Conversation.objects.get_or_create(user=user)
        # Lock the row so two quick messages from one user are routed one after the other.
        conversation = Conversation.objects.select_for_update().get(user=user)
        user.last_inbound_at = timezone.now()
        user.save(update_fields=["last_inbound_at"])
        return route(Context(user=user, conversation=conversation, msg=msg))
