from django.db import models

from .names import normalize_name
from .phone import normalize_cm_number
from .prefixes import operator_for


class PhoneNumber(models.Model):
    e164 = models.CharField(max_length=16, unique=True)
    operator = models.CharField(max_length=20)
    first_seen = models.DateTimeField(auto_now_add=True)
    check_count = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.e164


class AccountName(models.Model):
    class Provider(models.TextChoices):
        MOMO = "momo"
        OM = "om"
        UNKNOWN = "unknown"

    normalized = models.CharField(max_length=255)
    display_raw = models.CharField(max_length=255)
    provider = models.CharField(max_length=10, choices=Provider.choices, default=Provider.UNKNOWN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["normalized", "provider"], name="unique_account_name_per_provider"
            )
        ]

    def __str__(self) -> str:
        return self.display_raw


def get_or_create_phone(raw: str) -> PhoneNumber | None:
    """Store a Cameroonian number once. Returns None if the input is not a valid CM number."""
    e164 = normalize_cm_number(raw)
    if e164 is None:
        return None
    phone, _ = PhoneNumber.objects.get_or_create(
        e164=e164, defaults={"operator": operator_for(e164)}
    )
    return phone


def get_or_create_account_name(raw: str, provider: str = "unknown") -> AccountName | None:
    """Store an account name once per normalised form and provider. None for a blank name."""
    normalized = normalize_name(raw)
    if not normalized:
        return None
    account, _ = AccountName.objects.get_or_create(
        normalized=normalized, provider=provider, defaults={"display_raw": raw.strip()}
    )
    return account
