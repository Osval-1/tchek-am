from collections.abc import Callable
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from tchekam.core.tasks import enqueue
from tchekam.messaging.channel import InboundMessage

from .models import BotUser, Conversation
from .router import Context, Reply, route


@dataclass
class HookResult:
    """Replies to send BEFORE the routed ones (e.g. a queued notification ahead of the menu).

    `on_delivered` runs only once `deliver` succeeded, so a failed send loses nothing.
    """

    replies: list[Reply] = field(default_factory=list)
    on_delivered: Callable[[], None] | None = None


# Hooks run after routing, inside the locked transaction.
AfterRouteHook = Callable[[BotUser, Conversation, list[Reply]], HookResult]
_AFTER_ROUTE_HOOKS: list[AfterRouteHook] = []


def register_after_route_hook(fn: AfterRouteHook) -> None:
    if fn not in _AFTER_ROUTE_HOOKS:  # register() may run more than once (tests, reloads)
        _AFTER_ROUTE_HOOKS.append(fn)


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
    delivered_callbacks: list[Callable[[], None]] = []
    with transaction.atomic():
        user, _ = BotUser.objects.get_or_create(wa_phone=f"+{msg.sender_phone}")
        Conversation.objects.get_or_create(user=user)
        # Lock the row so two quick messages from one user are routed one after the other.
        conversation = Conversation.objects.select_for_update().get(user=user)
        user.last_inbound_at = timezone.now()
        user.save(update_fields=["last_inbound_at"])
        ctx = Context(user=user, conversation=conversation, msg=msg)
        replies = route(ctx)
        if not user.blocked:
            early: list[Reply] = []
            for hook in _AFTER_ROUTE_HOOKS:
                result = hook(user, conversation, replies)
                early += result.replies
                if result.on_delivered:
                    delivered_callbacks.append(result.on_delivered)
            if early:
                conversation.save()  # a hook may have started a flow after route() saved
                replies = early + replies
    try:
        try:
            if deliver is not None:
                deliver(replies)
            for callback in delivered_callbacks:  # not reached when deliver raised
                callback()
        finally:
            for name, kwargs in ctx.jobs:
                enqueue(name, **kwargs)
    except Exception as exc:
        # Routing is committed: the caller must not run this message again (it would route twice).
        exc.after_commit = True  # type: ignore[attr-defined]
        raise
    return replies
