"""Month-year labels without a locale dependency (system locales differ per host)."""

import unicodedata
from datetime import date

_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
# Pidgin has no month names of its own: it uses the English ones.
_MONTHS = {"fr": _FR, "en": _EN, "pcm": _EN}


def month_year(d: date, lang: str | None) -> str:
    """ "mars 2026" / "March 2026". Unknown or missing language falls back to French."""
    names = _MONTHS.get(lang or "fr", _FR)
    return f"{names[d.month - 1]} {d.year}"


def _plain(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


# French and English names (Pidgin uses English), accent-free, plus common abbreviations.
_BY_NAME: dict[str, int] = {}
for _names in (_FR, _EN):
    for _i, _name in enumerate(_names, start=1):
        _BY_NAME[_plain(_name)] = _i
for _abbr, _i in {
    "janv": 1, "jan": 1, "fevr": 2, "feb": 2, "mar": 3, "avr": 4, "apr": 4, "juil": 7,
    "jul": 7, "aout": 8, "aug": 8, "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}.items():  # fmt: skip
    _BY_NAME[_abbr] = _i


def parse_month(name: str) -> int | None:
    """Month number (1-12) from a French or English month name or abbreviation, else None."""
    return _BY_NAME.get(_plain(name.strip().rstrip(".")))
