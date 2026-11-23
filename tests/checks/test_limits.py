import pytest

from tchekam.checks.limits import check_allowed
from tchekam.checks.models import CheckLog
from tchekam.conversations.models import BotUser

pytestmark = pytest.mark.django_db


def test_limit_counts_all_kinds_for_that_user_only(settings):
    settings.CHECKS_PER_DAY = 2
    me = BotUser.objects.create(wa_phone="+237670000010")
    other = BotUser.objects.create(wa_phone="+237670000011")
    CheckLog.objects.create(user=other, kind="number", subject_ref="x", result_band="green")
    CheckLog.objects.create(user=me, kind="number", subject_ref="x", result_band="green")
    assert check_allowed(me)
    CheckLog.objects.create(user=me, kind="image", subject_ref="y", result_band="none")
    assert not check_allowed(me)


def test_yesterdays_checks_do_not_count(settings):
    from datetime import timedelta

    from django.utils import timezone

    settings.CHECKS_PER_DAY = 1
    me = BotUser.objects.create(wa_phone="+237670000010")
    log = CheckLog.objects.create(user=me, kind="number", subject_ref="x", result_band="green")
    CheckLog.objects.filter(pk=log.pk).update(
        created_at=timezone.now() - timedelta(days=1, hours=1)
    )
    assert check_allowed(me)
