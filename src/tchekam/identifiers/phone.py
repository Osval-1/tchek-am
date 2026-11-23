import re

import phonenumbers

_SEPARATORS = re.compile(r"[\s.\-()]")
# Compact digit runs the matcher can miss, e.g. "00237655123456" or "677123456".
_COMPACT = re.compile(
    r"(?<![A-Za-z0-9])(?:00|\+)?237[62]\d{8}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])[62]\d{8}(?![A-Za-z0-9])"
)
# A currency token right after a candidate means it is an amount, e.g. "25000 FCFA".
_CURRENCY_AFTER = re.compile(r"\s*(?:F\s*CFA|FCFA|XAF|CFA|frs|francs|F)\b", re.IGNORECASE)
# Round amounts written as 3-3-3 groups ending in "000", e.g. "677 000 000" or "650.000.000".
# Other 3-3-3 groups ("677 123 456") are real mobile formats and are kept.
_THOUSANDS = re.compile(r"(?:\+|00)?(?:237[ .]?)?\d{3}[ .]\d{3}[ .]000")
_MOBILE_TYPES = {
    phonenumbers.PhoneNumberType.MOBILE,
    phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
}


def normalize_cm_number(raw: str) -> str | None:
    """Return the E.164 form of a Cameroonian number, or None if invalid or foreign.

    Accepts 9-digit national numbers starting with 6 or 2, and "+237", "00237" or "237" prefixes.
    Spaces, dots, dashes and parentheses are ignored.
    """
    cleaned = _SEPARATORS.sub("", raw)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if cleaned.isdigit() and len(cleaned) == 9 and cleaned[0] in "62":
        cleaned = "+237" + cleaned
    elif cleaned.isdigit() and len(cleaned) == 12 and cleaned.startswith("237"):
        cleaned = "+" + cleaned
    if not cleaned.startswith("+237"):
        return None
    try:
        parsed = phonenumbers.parse(cleaned, "CM")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def _is_isolated(text: str, start: int, end: int) -> bool:
    """Reject digits glued to letters, or to a dash/dot followed by a digit (refs, dates, IDs)."""
    if start > 0 and text[start - 1].isascii() and text[start - 1].isalnum():
        return False
    if end < len(text) and text[end].isascii() and text[end].isalnum():
        return False
    if end + 1 < len(text) and text[end] in "-." and text[end + 1].isdigit():
        return False
    if start > 1 and text[start - 1] in "-." and text[start - 2].isdigit():
        return False
    return True


def _candidate(text: str, start: int, end: int, raw: str) -> str | None:
    """Return the E.164 number for a raw match if it is a standalone Cameroonian mobile."""
    if not _is_isolated(text, start, end):
        return None
    if _CURRENCY_AFTER.match(text, end) or _THOUSANDS.fullmatch(raw):
        return None
    number = normalize_cm_number(raw)
    if number is None:
        return None
    if phonenumbers.number_type(phonenumbers.parse(number)) not in _MOBILE_TYPES:
        return None
    return number


def find_numbers(text: str) -> list[str]:
    """Return every Cameroonian mobile number in free text as unique E.164 strings, in order.

    Fixed lines, amounts, reference IDs and dates are excluded.
    """
    found: list[tuple[int, str]] = []
    for match in phonenumbers.PhoneNumberMatcher(text, "CM"):
        number = _candidate(text, match.start, match.end, match.raw_string)
        if number:
            found.append((match.start, number))
    for match in _COMPACT.finditer(text):
        number = _candidate(text, match.start(), match.end(), match.group())
        if number:
            found.append((match.start(), number))
    unique: dict[str, None] = {}
    for _, number in sorted(found):
        unique.setdefault(number)
    return list(unique)
