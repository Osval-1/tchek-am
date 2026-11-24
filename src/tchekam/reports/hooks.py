"""Extension points in the report flow."""

from .models import Report
from .scoring import refresh_evidence_score


def after_extraction(report: Report) -> None:
    """Called once AI extraction is stored. Web matches for the images arrive in Issue 19."""
    refresh_evidence_score(report)
