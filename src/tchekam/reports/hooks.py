"""Extension points in the report flow; later issues replace these no-ops."""

from .models import Report


def after_extraction(report: Report) -> None:
    """Called once AI extraction is stored. Web matches for the images arrive in Issue 19."""
