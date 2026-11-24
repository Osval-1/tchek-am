"""Extension points for inbound messages. Apps that depend on messaging plug in here."""

from collections.abc import Callable

from .channel import InboundMessage

GroupHandler = Callable[[InboundMessage], None]
_group_handler: GroupHandler | None = None


def register_group_handler(handler: GroupHandler) -> None:
    """Set the handler for group messages (tchekam.groups, Issue 20). The last one wins."""
    global _group_handler
    _group_handler = handler


def on_group_message(msg: InboundMessage) -> None:
    """Called from the process_inbound job for every inbound group message."""
    if _group_handler is not None:
        _group_handler(msg)
