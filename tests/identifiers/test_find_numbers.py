import pytest

from tchekam.identifiers.phone import find_numbers


def test_find_numbers_extracts_cameroonian_numbers_from_french_sentence():
    text = (
        "Appelez le +237 677 12 34 56 ou écrivez au 699-12-34-56, merci. "
        "Le numéro +33 6 12 34 56 78 est étranger."
    )

    assert find_numbers(text) == ["+237677123456", "+237699123456"]


def test_find_numbers_returns_unique_numbers_in_order_of_appearance():
    text = "Ancien 699 12 34 56, puis 677123456, puis encore +237 699 12 34 56"

    assert find_numbers(text) == ["+237699123456", "+237677123456"]


@pytest.mark.parametrize("text", ["envoyez 00237655123456 svp", "ref:655123456;ok"])
def test_find_numbers_finds_compact_forms(text):
    assert len(find_numbers(text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "6 77 12 34 56",
        "677-12-34-56",
        "+237 677 12 34 56",
        "Tel: (+237) 677.12.34.56",
        "677 123 456",
        "+237 677 123 456",
    ],
)
def test_find_numbers_finds_mobile_in_separator_formats(text):
    assert find_numbers(text) == ["+237677123456"]


def test_find_numbers_returns_empty_list_when_only_foreign_numbers():
    assert find_numbers("Mon numéro est +33 6 12 34 56 78") == []


@pytest.mark.parametrize(
    "text",
    [
        "25000 FCFA",
        "222 000 000 FCFA",
        "Montant 222000000 FCFA",
        "Solde 677 000 000 FCFA",
        "Solde: 650.000.000 FCFA",
        "677 000 000",
        "650.000.000",
        "montant 233 500 000 XAF",
        "ID transaction: 6771234567890",
        "Txn 20231015677123456",
        "MP231015.1234.A56789",
        "TX677123456AB",
        "A677123456",
        "677123456-1",
        "12/05/2024 10:22:33",
        "Appelez le 222 22 22 22",
    ],
)
def test_find_numbers_rejects_amounts_ids_and_fixed_lines(text):
    assert find_numbers(text) == []


def test_find_numbers_extracts_only_the_payee_from_momo_sms():
    text = (
        "Vous avez envoye 25000 FCFA a JEAN MBARGA (677123456) le 12/05/2024 10:22:33. "
        "ID transaction: 8812345678. Solde: 150 000 FCFA."
    )

    assert find_numbers(text) == ["+237677123456"]
