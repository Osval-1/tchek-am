"""Parsers for what the reporter types when editing the confirmation list.

Each returns None for input it cannot accept, so the handler can re-prompt without changing
anything. "-" (or none/aucun) means "clear this field" and is handled by the caller.
"""

import re
import unicodedata
from datetime import date, timedelta

from django.utils import timezone

from tchekam.i18n import parse_month
from tchekam.identifiers.names import normalize_name
from tchekam.identifiers.phone import find_numbers, normalize_cm_number

MAX_NAMES = 3
MAX_NAME_LEN = 60
MAX_SUMMARY_LEN = 500
MAX_EDIT_AMOUNT = 100_000_000
MAX_DATE_AGE = timedelta(days=5 * 365)
CLEAR_WORDS = frozenset({"-", "none", "aucun", "aucune"})

_NAME_SEPARATORS = re.compile(r"[,;\n]")
_AMOUNT = re.compile(
    r"(\d{1,3}(?:[ .,]\d{3}){1,4}|\d{1,15})\s*(?:f\s*cfa|fcfa|xaf|cfa|frs|f)?",
    re.IGNORECASE | re.ASCII,
)
_NUMERIC_DATE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})", re.ASCII)
_ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})", re.ASCII)
_WORD_DATE = re.compile(r"([0-9]{1,2})\s+([^\W\d_]+)\.?\s+([0-9]{4})")


def is_clear(text: str) -> bool:
    return text.strip().casefold() in CLEAR_WORDS


def clean(text: str) -> str:
    """Drop control and format characters, collapse whitespace."""
    kept = (
        " " if c.isspace() else c for c in text if c.isspace() or unicodedata.category(c)[0] != "C"
    )
    return " ".join("".join(kept).split())


def _looks_numeric(name: str) -> bool:
    """A phone number or mostly digits: not a name, and a number must not be stored as one."""
    digits = sum(c.isdecimal() for c in name)
    return digits * 2 > len(name) or bool(find_numbers(name) or normalize_cm_number(name))


def parse_names(text: str) -> list[str] | None:
    names = [n for part in _NAME_SEPARATORS.split(text) if (n := clean(part))]
    if not names or any(len(n) > MAX_NAME_LEN or _looks_numeric(n) for n in names):
        return None
    # Dedupe on the stored form (case and accents) before the cap, so variants take one slot.
    unique: dict[str, str] = {}
    for n in names:
        unique.setdefault(normalize_name(n), n)
    return list(unique.values())[:MAX_NAMES]


def parse_amount(text: str) -> int | None:
    match = _AMOUNT.fullmatch(text.strip())
    if match is None:
        return None
    value = int(re.sub(r"\D", "", match.group(1)))
    return value if 0 < value <= MAX_EDIT_AMOUNT else None


def parse_date(text: str) -> date | None:
    """dd/mm/yyyy, dd-mm-yyyy, d/m/yy, yyyy-mm-dd, "12 mars 2026"; not in the future, not > 5 y."""
    text = text.strip()
    if m := _ISO_DATE.fullmatch(text):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif m := _NUMERIC_DATE.fullmatch(text):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        if len(m[3]) == 2:
            y += 2000
    elif m := _WORD_DATE.fullmatch(text):
        d, y = int(m[1]), int(m[3])
        mo = parse_month(m[2])
        if mo is None:
            return None
    else:
        return None
    try:
        value = date(y, mo, d)
    except ValueError:
        return None
    today = timezone.localdate()
    return value if today - MAX_DATE_AGE <= value <= today else None


def parse_summary(text: str) -> str | None:
    value = clean(text)
    return value if value and len(value) <= MAX_SUMMARY_LEN else None
