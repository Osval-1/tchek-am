import pytest

from tchekam.identifiers.names import mask_name, normalize_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Éloïse   Ndjock ", "ELOISE NDJOCK"),
        ("jean-paul mbarga", "JEAN-PAUL MBARGA"),
        ("", ""),
    ],
)
def test_normalize_name_uppercases_strips_accents_and_collapses_whitespace(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Hyphenated word: first hyphen-part whole, then first letter of the next part + ***.
        ("Jean-Paul Mbarga", "JEAN-P*** M***"),
        # Plain word: first letter + ***.
        ("Ngono", "N***"),
        ("Éloïse Ndjock", "E*** N***"),
        # Single-letter words stay as they are.
        ("Jean A", "J*** A"),
        # Hyphen rule with a single-letter first part: first part kept, next letter + ***.
        ("A-B", "A-B***"),
        ("", ""),
    ],
)
def test_mask_name_hides_all_but_initials(raw, expected):
    assert mask_name(raw) == expected
