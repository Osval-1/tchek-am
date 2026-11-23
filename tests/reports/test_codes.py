import re

import pytest

from tchekam.conversations.models import BotUser
from tchekam.reports import codes
from tchekam.reports.models import Report

pytestmark = pytest.mark.django_db


def test_new_code_shape():
    for _ in range(200):
        assert re.fullmatch(r"TA-[A-HJ-NP-Z2-9]{5}", codes.new_code())


def test_assign_reference_retries_on_collision(monkeypatch):
    user = BotUser.objects.create(wa_phone="+237670000001")
    Report.objects.create(reporter=user, reference="TA-AAAAA")
    report = Report.objects.create(reporter=user)
    candidates = iter(["TA-AAAAA", "TA-AAAAA", "TA-BBBBB"])
    monkeypatch.setattr(codes, "new_code", lambda: next(candidates))

    assert codes.assign_reference(report) == "TA-BBBBB"
    report.refresh_from_db()
    assert report.reference == "TA-BBBBB"


def test_assign_reference_gives_up(monkeypatch):
    user = BotUser.objects.create(wa_phone="+237670000001")
    Report.objects.create(reporter=user, reference="TA-AAAAA")
    report = Report.objects.create(reporter=user)
    monkeypatch.setattr(codes, "new_code", lambda: "TA-AAAAA")

    with pytest.raises(RuntimeError):
        codes.assign_reference(report)
