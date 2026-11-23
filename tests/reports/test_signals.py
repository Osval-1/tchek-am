import pytest

from tchekam.conversations.models import BotUser
from tchekam.reports.models import Report
from tchekam.reports.signals import report_status_changed
from tchekam.reports.transitions import InvalidTransition

pytestmark = pytest.mark.django_db


@pytest.fixture
def received():
    events = []

    def receiver(sender, report, from_status, to_status, **kwargs):
        events.append((sender, report.pk, from_status, to_status))

    report_status_changed.connect(receiver, dispatch_uid="test-receiver")
    yield events
    report_status_changed.disconnect(dispatch_uid="test-receiver")


@pytest.fixture
def report():
    return Report.objects.create(reporter=BotUser.objects.create(wa_phone="+237600000001"))


def test_transition_sends_signal_after_commit(report, received, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        report.transition("pending")
        assert received == []  # nothing before commit
    assert received == [(Report, report.pk, "draft", "pending")]


def test_merge_sends_signal_after_commit(report, received, django_capture_on_commit_callbacks):
    target = Report.objects.create(reporter=report.reporter, status="pending")
    report.status = "pending"
    report.save()
    with django_capture_on_commit_callbacks(execute=True):
        report.merge_into(target)
    assert received == [(Report, report.pk, "pending", "merged")]


def test_invalid_transition_sends_nothing(report, received, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True), pytest.raises(InvalidTransition):
        report.transition("approved")
    assert received == []
