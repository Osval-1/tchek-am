from datetime import date

import pytest

from tchekam.appeals.dates import parse_acquired_month

TODAY = date(2026, 11, 24)


@pytest.mark.parametrize(
    "text",
    ["06/2026", "6/2026", "06-2026", "6 2026", "2026-06", "juin 2026", "June 2026", "juin de 2026"]
    + ["JUIN 2026", "  june   2026 "],
)
def test_accepts_month_and_year(text):
    assert parse_acquired_month(text, TODAY) == date(2026, 6, 1)


@pytest.mark.parametrize(
    "text",
    ["", "hello", "13/2026", "00/2026", "06/26", "12/2026", "juin 1999", "06/1900", "2026"]
    + ["foo 2026", "677123456", "1/2/2026"],
)
def test_rejects_unusable_dates(text):
    assert parse_acquired_month(text, TODAY) is None


def test_current_month_is_allowed_but_not_the_next():
    assert parse_acquired_month("11/2026", TODAY) == date(2026, 11, 1)
    assert parse_acquired_month("12/2026", TODAY) is None
