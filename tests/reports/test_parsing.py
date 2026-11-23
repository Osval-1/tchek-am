from datetime import date, timedelta

import pytest
from django.utils import timezone

from tchekam.i18n import parse_month
from tchekam.reports import parsing


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("25000", 25000),
        ("25 000", 25000),
        ("25.000", 25000),
        ("1,250,000 FCFA", 1250000),
        ("5000 xaf", 5000),
        ("5000F", 5000),
        ("100000000", 100_000_000),
    ],
)
def test_amount_accepts_separators_and_currency(text, value):
    assert parsing.parse_amount(text) == value


@pytest.mark.parametrize("text", ["0", "100000001", "abc", "12,5", "25000 euros", ""])
def test_amount_rejects(text):
    assert parsing.parse_amount(text) is None


def test_dates_in_every_accepted_format():
    expected = date(2026, 3, 12)
    for text in [
        "12/03/2026",
        "12-03-2026",
        "12/3/26",
        "2026-03-12",
        "12 mars 2026",
        "12 March 2026",
    ]:
        assert parsing.parse_date(text) == expected, text


@pytest.mark.parametrize("text", ["31/02/2026", "12 foo 2026", "hier", "2026/03/12"])
def test_date_rejects_garbage(text):
    assert parsing.parse_date(text) is None


def test_date_rejects_future_and_old():
    today = timezone.localdate()
    assert parsing.parse_date(today.strftime("%d/%m/%Y")) == today
    assert parsing.parse_date((today + timedelta(days=1)).strftime("%d/%m/%Y")) is None
    assert parsing.parse_date((today - timedelta(days=6 * 365)).isoformat()) is None


def test_names_split_dedupe_cap_and_strip_control_chars():
    assert parsing.parse_names("Jean Dupont; Marie Ngo\nPaul\x07 X, Zed") == [
        "Jean Dupont",
        "Marie Ngo",
        "Paul X",
    ]
    assert parsing.parse_names("Jean Dupont, jean dupont, Jéan DUPONT, Bob") == [
        "Jean Dupont",
        "Bob",
    ]
    assert parsing.parse_names(" , ;") is None
    assert parsing.parse_names("x" * 61) is None
    assert parsing.parse_names("x" * 60) == ["x" * 60]


@pytest.mark.parametrize("text", ["677123456", "Pay 677 12 34 56", "12345 ab", "Jean, 655112233"])
def test_names_reject_numbers(text):
    assert parsing.parse_names(text) is None


@pytest.mark.parametrize("text", ["٢٥٠٠٠", "²³", "①", "1" * 4000, "😀"])
def test_amount_and_date_never_raise_on_odd_digits(text):
    assert parsing.parse_amount(text) is None or isinstance(parsing.parse_amount(text), int)
    assert parsing.parse_date(text) is None
    assert parsing.parse_date(f"1/1/{text}") is None


def test_summary_limits_and_cleaning():
    assert parsing.parse_summary("  hello‮   world \n") == "hello world"
    assert parsing.parse_summary("x" * 501) is None
    assert parsing.parse_summary(" \u0000 ") is None


def test_clear_words():
    assert all(parsing.is_clear(w) for w in ["-", "none", "Aucun", " AUCUNE "])
    assert not parsing.is_clear("no")


def test_parse_month_names_and_abbreviations():
    assert parse_month("mars") == 3
    assert parse_month("Février") == 2
    assert parse_month("AUGUST") == 8
    assert parse_month("janv.") == 1
    assert parse_month("nope") is None


def test_parse_details_survives_huge_digit_runs():
    from tchekam.reports.flow import parse_details

    assert parse_details("9" * 5000) == ([], None)
    parse_details("1 " + "000 " * 2000)  # must not raise
    assert parse_details("677123456 25000")[1] == 25000
    assert parsing.parse_amount("9" * 5000) is None
    assert parsing.parse_amount(" ".join(["000"] * 2000)) is None
