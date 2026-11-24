"""Issue 16: reporter weighting (R3), the weekly limit, and its effect on bands."""

from datetime import timedelta
from itertools import count

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.i18n import t
from tchekam.identifiers.models import get_or_create_phone
from tchekam.moderation import service as moderation
from tchekam.reports.limits import limit_notice, weekly_limit_reached
from tchekam.reports.models import Report, ReportSubject
from tchekam.reports.weighting import is_limited, recompute, trust_weight
from tchekam.reputation.facts import Band
from tchekam.reputation.service import band_for_phone, cache_key

pytestmark = pytest.mark.django_db

SELLER = "+237677123456"
OTHER = "+237677654321"
_n = count(1)


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()


@pytest.fixture
def mod(db):
    return get_user_model().objects.create_user("mod", password="x", is_staff=True)


def reporter():
    return BotUser.objects.create(wa_phone=f"+2376400{next(_n):05d}", language="en")


def report(user, status="pending", number=SELLER, confirmed=True, **kw) -> Report:
    when = timezone.now() - timedelta(days=2)
    r = Report.objects.create(
        reporter=user, status=status, reference=f"TA-{next(_n):05d}", submitted_at=when,
        decided_at=when if status in ("approved", "rejected") else None, **kw,
    )  # fmt: skip
    ReportSubject.objects.create(
        report=r, phone_number=get_or_create_phone(number), role="seller", source="ai",
        confirmed=confirmed,
    )  # fmt: skip
    return r


def reject(r, mod):
    row = Report.objects.get(pk=r.pk)
    data = QueryDict(mutable=True)
    data.update(
        {
            "action": "reject",
            "reason_code": "insufficient_evidence",
            "state_token": moderation.state_token(row),
        }
    )
    with TestCase.captureOnCommitCallbacks(execute=True):
        moderation.decide(r.pk, mod, data)


# Pure formula ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("approved", "rejected", "expected"),
    [
        (0, 0, 0.5),
        (1, 0, 2 / 3),
        (0, 1, 1 / 3),
        (0, 3, 0.2),
        (1, 3, 1 / 3),
        (1, 4, 2 / 7),
        (9, 0, 10 / 11),
    ],
)
def test_trust_weight_formula(approved, rejected, expected):
    assert trust_weight(approved, rejected) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("weight", "rejected", "limited"),
    [
        (0.2, 3, True),
        (0.2, 2, False),  # not enough rejections
        (0.3, 3, False),  # the weight bound is strict
        (0.29, 3, True),
        (0.2, 10, True),
        (1.0, 0, False),
    ],
)
def test_is_limited_boundaries(weight, rejected, limited):
    assert is_limited(weight, rejected) is limited


# Recompute through the moderation path ---------------------------------------------------------


def test_three_rejections_give_weight_point_two_and_a_weekly_limit(mod):
    user = reporter()
    reports = [report(user, number=f"+23767700000{i}") for i in range(3)]

    for i, r in enumerate(reports, start=1):
        reject(r, mod)
        user.refresh_from_db()
        assert user.trust_weight == pytest.approx(trust_weight(0, i))

    assert user.trust_weight == pytest.approx(0.2)
    assert weekly_limit_reached(user)  # the rejected reports were submitted two days ago
    assert limit_notice(user) == ("report.limit_reached_weekly", {})


def test_limited_reporter_may_submit_again_after_a_week(mod):
    user = reporter()
    for i in range(3):
        report(user, status="rejected", number=f"+23767700000{i}")
    recompute(user)
    old = report(user, number=OTHER)
    Report.objects.filter(pk=old.pk).update(submitted_at=timezone.now() - timedelta(days=8))
    Report.objects.filter(reporter=user).update(submitted_at=timezone.now() - timedelta(days=8))

    assert not weekly_limit_reached(user)


def test_unlimited_reporter_is_not_held_to_a_week(mod):
    user = reporter()
    report(user)  # one pending report today
    assert not weekly_limit_reached(user)
    assert limit_notice(user) is None


def test_daily_limit_message_wins_when_both_apply(mod, settings):
    settings.REPORTS_PER_DAY = 1
    user = reporter()
    for i in range(3):
        report(user, status="rejected", number=f"+23767700000{i}")
    recompute(user)
    Report.objects.filter(reporter=user).update(submitted_at=timezone.now())

    assert limit_notice(user) == ("report.limit_reached", {"n": 1})


def test_reopen_undoes_a_rejection(mod):
    user = reporter()
    r = report(user)
    reject(r, mod)
    user.refresh_from_db()
    assert user.trust_weight == pytest.approx(1 / 3)

    row = Report.objects.get(pk=r.pk)
    data = QueryDict(mutable=True)
    data.update(
        {"action": "reopen", "reopen_reason": "appeal", "state_token": moderation.state_token(row)}
    )
    with TestCase.captureOnCommitCallbacks(execute=True):
        moderation.decide(r.pk, mod, data)

    user.refresh_from_db()
    assert user.trust_weight == pytest.approx(0.5)


def test_recompute_without_change_invalidates_nothing():
    user = reporter()
    report(user)
    assert recompute(user) == {SELLER}  # weight 1.0 -> 0.5 is a change: those bands must refresh
    assert recompute(user) == set()  # a second run changes nothing


# Bands: Issue 7 integration --------------------------------------------------------------------


def test_low_trust_reporter_stops_counting_as_independent_immediately(mod):
    low = reporter()
    approved_low = report(low, status="approved")
    for _ in range(2):
        report(reporter(), status="approved")
    for i in range(4):  # 1 approved + 4 rejected: (1+1)/(1+4+2) = 0.286
        report(low, status="pending", number=f"+23767700000{i}")
    pending = list(Report.objects.filter(reporter=low, status="pending"))

    before = band_for_phone(SELLER)
    assert (before.band, before.independent_reporters) == (Band.RED, 3)
    assert cache.get(cache_key(SELLER)) is not None  # warm: only invalidation can update it

    for r in pending[:3]:
        reject(r, mod)
    low.refresh_from_db()
    assert low.trust_weight == pytest.approx(1 / 3)  # still counts, so nothing changed
    assert band_for_phone(SELLER).band == Band.RED

    reject(pending[3], mod)

    low.refresh_from_db()
    assert low.trust_weight < 0.3 and is_limited(low.trust_weight, 4)
    after = band_for_phone(SELLER)
    assert (after.band, after.independent_reporters) == (Band.ORANGE, 2)
    assert approved_low.status == "approved"  # the report itself is untouched


# Moderator warning ------------------------------------------------------------------------------


def test_review_page_warns_about_a_limited_reporter(mod, otp_login, client):
    user = reporter()
    for i in range(3):
        report(user, status="rejected", number=f"+23767700000{i}")
    recompute(user)
    current = report(user, number=OTHER)
    otp_login(client, mod)

    page = client.get(reverse("moderation:review", args=[current.pk])).content.decode()

    assert "low-trust reporter" in page
    assert user.wa_phone not in page


def test_review_page_has_no_warning_for_a_normal_reporter(mod, otp_login, client):
    current = report(reporter())
    otp_login(client, mod)

    page = client.get(reverse("moderation:review", args=[current.pk])).content.decode()

    assert "low-trust reporter" not in page


def test_weekly_limit_message_exists_in_every_language():
    for lang in ("fr", "en", "pcm"):
        assert t("report.limit_reached_weekly", lang)
