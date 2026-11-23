import pytest

from tchekam.identifiers.prefixes import operator_for


@pytest.mark.parametrize(
    ("e164", "operator"),
    [
        ("+237677123456", "MTN"),
        ("+237650123456", "MTN"),
        ("+237685123456", "MTN"),
        ("+237691234567", "Orange"),
        ("+237655123456", "Orange"),
        ("+237640123456", "Orange"),
        ("+237661234567", "Nexttel"),
        ("+237622123456", "Camtel"),
        ("+237222123456", "Camtel"),
        ("+237600123456", "Unknown"),
    ],
)
def test_operator_for_returns_operator_for_prefix_group(e164, operator):
    assert operator_for(e164) == operator
