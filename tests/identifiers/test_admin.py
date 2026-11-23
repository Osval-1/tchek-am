from django.contrib import admin

from tchekam.identifiers.models import AccountName, PhoneNumber


def test_phone_number_is_registered_in_admin_and_searchable_by_e164():
    model_admin = admin.site._registry[PhoneNumber]

    assert "e164" in model_admin.search_fields


def test_account_name_is_registered_in_admin_and_searchable_by_normalised_name():
    model_admin = admin.site._registry[AccountName]

    assert "normalized" in model_admin.search_fields
