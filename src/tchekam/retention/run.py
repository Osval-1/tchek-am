"""One retention run: every rule, failures isolated, one audit entry with the counts."""

import logging
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from tchekam.core.audit import audit

from .rules import RULES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunResult:
    counts: dict[str, int]  # rule name -> rows deleted or minimised (or due, in a dry run)
    errors: dict[str, str]  # rule name -> exception class name
    dry_run: bool


def run_retention(now: datetime | None = None, dry_run: bool = False) -> RunResult:
    """Apply every rule (ADR-013). A failing rule is logged by class name and reported in the
    audit entry; the other rules still run. A dry run counts what is due, changes nothing and
    writes no audit entry."""
    now = now or timezone.now()
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for rule in RULES:
        try:
            counts[rule.name] = rule(now, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001  one rule must never stop the others
            errors[rule.name] = type(exc).__name__
            logger.warning("retention: rule %s failed: %s", rule.name, type(exc).__name__)
    if not dry_run:
        # Counts and class names only: never personal data.
        audit(None, "retention.run", counts=counts, errors=errors)
    return RunResult(counts=counts, errors=errors, dry_run=dry_run)
