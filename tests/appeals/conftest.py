from datetime import timedelta
from itertools import count

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from tchekam.appeals.provider import appeal_state
from tchekam.conversations.models import BotUser
from tchekam.identifiers.models import get_or_create_phone
from tchekam.reports.models import Report, ReportSubject
from tchekam.reputation import appeals_hook

from ..reports.conftest import SENDER, Bot  # noqa: F401
from ..reports.conftest import bot as bot  # noqa: F401  (fixture)

OWN = f"+{SENDER}"
_n = count(1)


@pytest.fixture(autouse=True)
def _appeals_wired():
    """Other test modules reset the provider; appeals tests need the real one."""
    cache.clear()
    appeals_hook.set_provider(appeal_state)
    yield
    cache.clear()


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user("mod", password="x", is_staff=True)


@pytest.fixture
def make_report(db):
    """An approved, confirmed report with payment proof about `phone` (one is enough for red)."""

    def make(incident, phone=OWN, status="approved", proof=True, submitted_ago=timedelta(hours=1)):
        reporter = BotUser.objects.create(wa_phone=f"+23769900{next(_n):04d}")
        report = Report.objects.create(
            reporter=reporter,
            status=status,
            reference=f"TA-{next(_n):05d}",
            has_payment_proof=proof,
            submitted_at=timezone.now() - submitted_ago,
            decided_at=timezone.now(),
            incident_date=incident,
        )
        ReportSubject.objects.create(
            report=report,
            phone_number=get_or_create_phone(phone),
            role="seller",
            source="ai",
            confirmed=True,
        )
        return report

    return make


def months_ago(n: int):
    """First day of the month n months back."""
    today = timezone.localdate().replace(day=1)
    year, month = divmod(today.year * 12 + today.month - 1 - n, 12)
    return today.replace(year=year, month=month + 1)
