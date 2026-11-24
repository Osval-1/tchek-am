"""Month and year of acquiring a number, from what people type."""

import re
from datetime import date

from tchekam.i18n import parse_month

EARLIEST_YEAR = 2000  # mobile numbers did not exist in Cameroon before this
_NUMERIC = re.compile(r"^(\d{1,2})\s*[/.\-\s]\s*(\d{4})$")
_ISO = re.compile(r"^(\d{4})\s*[/.\-\s]\s*(\d{1,2})$")
_NAMED = re.compile(r"^([^\W\d_]+)\.?\s*(?:de\s+|of\s+|[/.\-])?\s*(\d{4})$")


def parse_acquired_month(text: str, today: date) -> date | None:
    """First day of the month in `text` ("06/2026", "2026-06", "juin 2026", "June 2026").

    None when the text is not a month and year, the year is absurd, or the month is in the future.
    """
    raw = " ".join(text.split())
    month = year = None
    if m := _NUMERIC.match(raw):
        month, year = int(m.group(1)), int(m.group(2))
    elif m := _ISO.match(raw):
        year, month = int(m.group(1)), int(m.group(2))
    elif m := _NAMED.match(raw):
        month, year = parse_month(m.group(1)), int(m.group(2))
    if month is None or year is None or not 1 <= month <= 12 or year < EARLIEST_YEAR:
        return None
    first = date(year, month, 1)
    return first if first <= today.replace(day=1) else None
