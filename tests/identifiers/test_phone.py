import pytest

from tchekam.identifiers.phone import normalize_cm_number


@pytest.mark.parametrize(
    "raw",
    [
        "677123456",
        "677 12 34 56",
        "677.12.34.56",
        "677-12-34-56",
        "(677) 12 34 56",
        "+237677123456",
        "+237 677 12 34 56",
        "+237-677-12-34-56",
        "00237677123456",
        "00237 677 12 34 56",
        "237677123456",
        "237 677 12 34 56",
        "699123456",
        "655 123 456",
        "662 123 456",
        "222 12 34 56",
        " 677123456 ",
    ],
)
def test_normalize_returns_e164_for_cameroonian_formats(raw):
    expected = "+237" + "".join(c for c in raw.strip() if c.isdigit())[-9:]

    assert normalize_cm_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "12345", "677 12 34", "abc", "+33 6 12 34 56 78", "+1 202 555 0100", "577123456"],
)
def test_normalize_returns_none_for_invalid_or_foreign(raw):
    assert normalize_cm_number(raw) is None
