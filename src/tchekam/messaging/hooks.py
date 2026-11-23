"""Extension points for inbound messages; later issues replace these no-ops."""

from .channel import InboundMessage


def on_group_message(msg: InboundMessage) -> None:
    """Called for every inbound group message. Group listening (Issue 20) fills this in."""
