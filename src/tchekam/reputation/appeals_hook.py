"""Where reputation reads appeal state. Issue 22 (appeals) installs the real provider.

Kept as a replaceable function so reputation never imports the appeals app: appeals depends
on reputation (to invalidate bands), not the other way round.
"""

from collections.abc import Callable

from .facts import NO_APPEAL, AppealState

AppealProvider = Callable[[str], AppealState]


def _no_appeals(e164: str) -> AppealState:
    return NO_APPEAL


_provider: AppealProvider = _no_appeals


def set_provider(provider: AppealProvider | None) -> None:
    """Install the appeal lookup. None restores the default (no appeals)."""
    global _provider
    _provider = provider or _no_appeals


def get_appeal_state(e164: str) -> AppealState:
    return _provider(e164)
