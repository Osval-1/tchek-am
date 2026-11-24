"""Where reputation reads the trust of reporters whose account link is gone (erased/anonymised).

Retention (ISSUES.md Issue 24) installs the real provider, backed by ReporterTrust. Kept as a
replaceable function so reputation never imports retention (same pattern as appeals_hook).
"""

from collections.abc import Callable, Mapping

TrustProvider = Callable[[frozenset[str]], Mapping[str, float]]


def _nobody(keys: frozenset[str]) -> Mapping[str, float]:
    return {}


_provider: TrustProvider = _nobody


def set_provider(provider: TrustProvider | None) -> None:
    """Install the trust lookup. None restores the default (no surviving trust)."""
    global _provider
    _provider = provider or _nobody


def erased_trust(keys: frozenset[str]) -> Mapping[str, float]:
    """reporter_key -> trust weight, for the keys that have one. Missing keys have none."""
    return _provider(keys)
