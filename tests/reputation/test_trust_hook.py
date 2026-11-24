"""The erased-reporter trust seam: reputation reads surviving trust without importing retention."""

from datetime import timedelta

import pytest
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.identifiers.models import PhoneNumber
from tchekam.reports.models import Report, ReportSubject
from tchekam.reputation import trust_hook
from tchekam.reputation.service import ERASED_REPORTER_TRUST, band_for_phone

SELLER = "+237690001234"


@pytest.fixture
def restore_provider():
    original = trust_hook._provider
    yield
    trust_hook.set_provider(original)


def test_default_provider_knows_nobody(restore_provider):
    trust_hook.set_provider(None)

    assert trust_hook.erased_trust(frozenset({"k"})) == {}


def test_installed_provider_is_used(restore_provider):
    trust_hook.set_provider(lambda keys: {k: 0.7 for k in keys})

    assert trust_hook.erased_trust(frozenset({"k"})) == {"k": 0.7}


def _erased_report_with_proof(key: str) -> None:
    phone = PhoneNumber.objects.create(e164=SELLER, operator="mtn")
    user = BotUser.objects.create(wa_phone="+237670009999")
    r = Report.objects.create(
        reporter=user,
        status=Report.Status.APPROVED,
        has_payment_proof=True,
        decided_at=timezone.now() - timedelta(days=5),
    )
    ReportSubject.objects.create(
        report=r, phone_number=phone, role="seller", source="moderator", confirmed=True
    )
    Report.objects.filter(pk=r.pk).update(reporter=None, reporter_key=key)


@pytest.mark.django_db
def test_erased_reporter_uses_surviving_trust(restore_provider):
    seen = []

    def provider(keys):
        seen.append(keys)
        return {"erased-key": 0.9}

    trust_hook.set_provider(provider)
    _erased_report_with_proof("erased-key")

    assert band_for_phone(SELLER, now=timezone.now()).band == "red"
    assert seen == [frozenset({"erased-key"})]


@pytest.mark.django_db
def test_erased_reporter_without_a_record_has_no_trust(restore_provider):
    trust_hook.set_provider(lambda keys: {})
    _erased_report_with_proof("erased-key")

    assert ERASED_REPORTER_TRUST == 0.0
    assert band_for_phone(SELLER, now=timezone.now()).band == "orange"
