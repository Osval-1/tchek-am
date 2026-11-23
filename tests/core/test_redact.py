import logging
import sys

import pytest

from tchekam.core.redact import RedactingFilter, redact


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+237677123456", "+237*******56"),
        ("677123456", "*******56"),
        ("call 677 123 456 now", "call *******56 now"),
        ("no digits here", "no digits here"),
        ("order 1234567", "order 1234567"),
    ],
)
def test_redact_masks_phone_numbers(raw, expected):
    assert redact(raw) == expected


def test_redact_truncates_long_text():
    out = redact("a" * 200)

    assert out == "a" * 80 + "…"


def test_redact_coerces_non_strings():
    assert redact(None) == "None"


def test_filter_redacts_formatted_message():
    record = logging.LogRecord("x", logging.INFO, "f", 1, "from %s", ("+237677123456",), None)

    assert RedactingFilter().filter(record) is True
    assert record.getMessage() == "from +237*******56"


def test_filter_survives_bad_format_args():
    record = logging.LogRecord("x", logging.INFO, "f", 1, "%d items", ("nope",), None)

    assert RedactingFilter().filter(record) is True
    assert record.msg == "%d items"


def test_filter_masks_exception_text():
    try:
        raise ValueError("bad number +237677123456")
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, "f", 1, "failed", None, sys.exc_info())

    RedactingFilter().filter(record)

    assert record.exc_info is None
    assert "+237*******56" in record.exc_text
    assert "677123456" not in record.exc_text
    assert "ValueError" in logging.Formatter().format(record)


def test_filter_masks_stack_info():
    record = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
    record.stack_info = "frame +237677123456"

    RedactingFilter().filter(record)

    assert "677123456" not in record.stack_info
