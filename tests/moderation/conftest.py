from datetime import timedelta
from itertools import count

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.identifiers.models import get_or_create_phone
from tchekam.reports.models import Evidence, Report, ReportSubject
from tchekam.reputation.service import band_for_phone, cache_key

_n = count(1)

SELLER = "+237677123456"
REPORTER = "+237699000111"


@pytest.fixture(autouse=True)
def _clean_cache():
    """Bands are cached per number; tests reuse numbers, so start each with an empty cache."""
    from django.core.cache import cache

    cache.clear()


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user("mod", password="x", is_staff=True)


@pytest.fixture
def plain_user(db):
    return get_user_model().objects.create_user("plain", password="x")


@pytest.fixture
def staff_client(client, staff, otp_login):
    otp_login(client, staff)
    return client


@pytest.fixture
def plain_client(plain_user, otp_login):
    c = Client()
    otp_login(c, plain_user)  # verified, yet still not staff
    return c


@pytest.fixture
def make_report(db, object_store):
    def make(
        status="pending",
        phone=SELLER,
        confirmed=False,
        reporter_phone=None,
        scam_type="momo_fraud",
        evidence_score=0.0,
        proof=False,
        files=1,
        submitted_ago=timedelta(hours=1),
        incident_date=None,
        **kw,
    ):
        reporter = BotUser.objects.create(wa_phone=reporter_phone or f"+23767000{next(_n):04d}")
        r = Report.objects.create(
            reporter=reporter,
            status=status,
            reference=f"TA-{next(_n):05d}",
            scam_type=scam_type,
            evidence_score=evidence_score,
            has_payment_proof=proof,
            submitted_at=timezone.now() - submitted_ago,
            incident_date=incident_date or timezone.localdate() - timedelta(days=3),
            decided_at=timezone.now() if status == "approved" else None,
            **kw,
        )
        for _ in range(files):
            key = f"evidence/secret-{next(_n)}"
            object_store.put(key, b"x", "image/png")
            Evidence.objects.create(
                report=r, kind="chat", object_key=key, mimetype="image/png",
                sha256=f"{next(_n):064d}", size_bytes=1,
            )  # fmt: skip
        if phone:
            ReportSubject.objects.create(
                report=r, phone_number=get_or_create_phone(phone), role="seller",
                source="ai", confirmed=confirmed,
            )  # fmt: skip
        return r

    return make


def state_token(report):
    from tchekam.moderation.service import state_token as token

    return token(Report.objects.get(pk=report.pk))


def post_data(report, **fields):
    """A complete review-form POST for `report` as the page would send it."""
    r = Report.objects.get(pk=report.pk)
    data = {"state_token": state_token(r), "edits": "1"}
    data["scam_type"] = r.scam_type
    if r.has_payment_proof:
        data["has_payment_proof"] = "on"
    if r.amount_xaf:
        data["amount_xaf"] = str(r.amount_xaf)
    if r.incident_date:
        data["incident_date"] = r.incident_date.isoformat()
    data["summary_final"] = r.summary_final
    for s in r.subjects.all():
        if s.confirmed:
            data[f"confirmed_{s.pk}"] = "on"
    data.update(fields)
    return data


def warm(e164=SELLER):
    """Compute and cache the band, so a later change proves the cache was invalidated."""
    result = band_for_phone(e164)
    from django.core.cache import cache

    assert cache.get(cache_key(e164)) is not None
    return result


@pytest.fixture
def post(staff_client, django_capture_on_commit_callbacks):
    """POST as staff, running on_commit hooks (cache invalidation, notify) like a real commit."""

    def do(url, data=None, client=None):
        with django_capture_on_commit_callbacks(execute=True):
            return (client or staff_client).post(url, data or {})

    return do
