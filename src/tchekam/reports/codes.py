"""Public reference codes for submitted reports, e.g. TA-7K3Q2."""

import secrets

from django.db import IntegrityError, transaction

from .models import Report

# No 0/O, 1/I: codes are read out and retyped, so look-alikes are left out.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 5
MAX_ATTEMPTS = 10


def new_code() -> str:
    return "TA-" + "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def assign_reference(report: Report) -> str:
    """Give the report a unique reference. The unique index decides, so races are retried."""
    for _ in range(MAX_ATTEMPTS):
        code = new_code()
        try:
            with transaction.atomic():  # a savepoint: the failed insert must not poison the caller
                Report.objects.filter(pk=report.pk).update(reference=code)
        except IntegrityError:
            continue
        report.reference = code
        return code
    raise RuntimeError("no free reference code")
