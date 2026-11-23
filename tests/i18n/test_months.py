from datetime import date

from tchekam.i18n import month_year


def test_month_year_per_language():
    d = date(2026, 3, 9)
    assert month_year(d, "fr") == "mars 2026"
    assert month_year(d, "en") == "March 2026"
    assert month_year(d, "pcm") == "March 2026"


def test_month_year_accents_and_fallback():
    assert month_year(date(2026, 2, 1), "fr") == "février 2026"
    assert month_year(date(2026, 8, 1), None) == "août 2026"
