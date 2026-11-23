"""Month-year labels without a locale dependency (system locales differ per host)."""

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
