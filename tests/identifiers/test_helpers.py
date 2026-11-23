import pytest

from tchekam.identifiers.models import (
    AccountName,
    PhoneNumber,
    get_or_create_account_name,
    get_or_create_phone,
)


@pytest.mark.django_db
def test_get_or_create_phone_stores_each_number_once():
    first = get_or_create_phone("677 12 34 56")
    second = get_or_create_phone("+237677123456")

    assert first.e164 == "+237677123456"
    assert first.operator == "MTN"
    assert first.pk == second.pk
    assert PhoneNumber.objects.count() == 1


@pytest.mark.django_db
def test_get_or_create_phone_returns_none_for_invalid_number():
    assert get_or_create_phone("+33 6 12 34 56 78") is None
    assert PhoneNumber.objects.count() == 0


@pytest.mark.django_db
def test_get_or_create_account_name_stores_normalised_name_and_raw_display():
    account = get_or_create_account_name("Jean-Paul Mbarga", provider="momo")

    assert account.normalized == "JEAN-PAUL MBARGA"
    assert account.display_raw == "Jean-Paul Mbarga"
    assert account.provider == "momo"


@pytest.mark.django_db
def test_get_or_create_account_name_is_unique_per_normalised_name_and_provider():
    first = get_or_create_account_name("éloïse ndjock", provider="om")
    second = get_or_create_account_name("ELOISE  NDJOCK", provider="om")
    other_provider = get_or_create_account_name("Eloise Ndjock", provider="momo")

    assert first.pk == second.pk
    assert other_provider.pk != first.pk
    assert AccountName.objects.count() == 2


@pytest.mark.django_db
def test_get_or_create_account_name_defaults_provider_to_unknown():
    assert get_or_create_account_name("Ngono").provider == "unknown"


@pytest.mark.django_db
def test_get_or_create_account_name_returns_none_for_blank_name():
    assert get_or_create_account_name("   ") is None
    assert AccountName.objects.count() == 0
