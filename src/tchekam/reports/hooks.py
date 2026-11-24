"""Extension points in the report flow."""

import logging

from tchekam.core.tasks import enqueue

from .models import Report
from .scoring import refresh_evidence_score

logger = logging.getLogger(__name__)


def after_extraction(report: Report) -> None:
    """Called once AI extraction is stored: rescore, and queue the web search for the images.

    Evidence kinds are only known now, which is why the web search starts here and not at
    upload. Runs inside extraction's catch-all, so the web part must never raise: a failed
    bonus check would otherwise send the reporter back to "analysis failed".
    """
    refresh_evidence_score(report)
    try:
        enqueue("reports.web_check", report_id=report.pk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reports.hooks: web check not queued: %s", type(exc).__name__)
