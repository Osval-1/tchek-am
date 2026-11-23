import hashlib
import hmac

import pytest
from django.db import IntegrityError, transaction
from django.test import override_settings

from tchekam.conversations.models import BotUser
from tchekam.reports.keys import reporter_key_for
from tchekam.reports.models import Report

pytestmark = pytest.mark.django_db

PHONE = "+237600000001"


def expected_key(phone: str, secret: str) -> str:
    return hmac.new(secret.encode(), phone.encode(), hashlib.sha256).hexdigest()


@override_settings(REPORTER_KEY_SECRET="s3cret")
def test_key_is_hmac_sha256_of_the_reporters_number():
    assert reporter_key_for(PHONE) == expected_key(PHONE, "s3cret")
    assert len(reporter_key_for(PHONE)) == 64


def test_key_depends_on_the_secret():
    with override_settings(REPORTER_KEY_SECRET="a"):
        a = reporter_key_for(PHONE)
    with override_settings(REPORTER_KEY_SECRET="b"):
        b = reporter_key_for(PHONE)
    assert a != b


def test_report_with_reporter_gets_a_key_on_create():
    user = BotUser.objects.create(wa_phone=PHONE)
    report = Report.objects.create(reporter=user)
    report.refresh_from_db()
    assert report.reporter_key == reporter_key_for(PHONE)


def test_report_without_reporter_has_blank_key():
    assert Report.objects.create().reporter_key == ""


def test_key_is_set_when_a_reporter_is_attached_later_with_update_fields():
    report = Report.objects.create()
    report.reporter = BotUser.objects.create(wa_phone=PHONE)
    report.save(update_fields=["reporter"])
    report.refresh_from_db()
    assert report.reporter_key == reporter_key_for(PHONE)


def test_existing_key_is_never_overwritten():
    report = Report.objects.create(reporter=BotUser.objects.create(wa_phone=PHONE))
    original = report.reporter_key
    with override_settings(REPORTER_KEY_SECRET="rotated"):
        report.save()
    report.refresh_from_db()
    assert report.reporter_key == original


def test_key_survives_reporter_erasure():
    user = BotUser.objects.create(wa_phone=PHONE)
    reports = [Report.objects.create(reporter=user) for _ in range(2)]
    user.delete()
    keys = {r.reporter_key for r in Report.objects.filter(pk__in=[r.pk for r in reports])}
    assert keys == {reporter_key_for(PHONE)}
    assert not Report.objects.filter(reporter__isnull=False).exists()


def test_same_reporter_same_key_different_reporter_different_key():
    a = BotUser.objects.create(wa_phone=PHONE)
    b = BotUser.objects.create(wa_phone="+237600000002")
    r1, r2, r3 = (Report.objects.create(reporter=u) for u in (a, a, b))
    assert r1.reporter_key == r2.reporter_key != r3.reporter_key


def test_db_rejects_a_live_reporter_without_a_key():
    report = Report.objects.create(reporter=BotUser.objects.create(wa_phone=PHONE))
    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.filter(pk=report.pk).update(reporter_key="")
    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.bulk_create([Report(reporter=report.reporter)])  # bypasses save()


def test_db_allows_a_blank_key_without_a_reporter():
    report = Report.objects.create()
    Report.objects.filter(pk=report.pk).update(reporter_key="")
