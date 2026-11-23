from collections.abc import Callable

from django.db import transaction
from django.utils import timezone

from tchekam.core.tasks import enqueue
from tchekam.messaging.channel import InboundMessage

from .models import BotUser, Conversation
from .router import Context, Reply, route


def handle_private_message(
    msg: InboundMessage, deliver: Callable[[list[Reply]], None] | None = None
) -> list[Reply]:
    """Load (or create) the sender's user and conversation, then route the message.

    Order: route and commit, then `deliver` the replies, then run the jobs handlers queued with
    `Context.enqueue_after`. Jobs run after the commit so workers see the saved state, and after
    delivery so their own messages arrive after the replies. They run even if delivery fails:
    the committed state already counts on them.
    """
    if not msg.sender_phone:
        return []
    with transaction.atomic():
        user, _ = BotUser.objects.get_or_create(wa_phone=f"+{msg.sender_phone}")
        Conversation.objects.get_or_create(user=user)
        # Lock the row so two quick messages from one user are routed one after the other.
        conversation = Conversation.objects.select_for_update().get(user=user)
        user.last_inbound_at = timezone.now()
        user.save(update_fields=["last_inbound_at"])
        ctx = Context(user=user, conversation=conversation, msg=msg)
        replies = route(ctx)
    try:
        if deliver is not None:
            deliver(replies)
    finally:
        for name, kwargs in ctx.jobs:
            enqueue(name, **kwargs)
    return replies
