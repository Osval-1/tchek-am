import pytest
from django.contrib.auth import get_user_model

from tchekam.conversations.models import BotUser
from tchekam.core.models import AuditLog
from tchekam.reports.models import Report
from tchekam.reports.transitions import ALLOWED, InvalidTransition

S = Report.Status
pytestmark = pytest.mark.django_db

VALID = [(src, dst) for src, dsts in ALLOWED.items() for dst in dsts]
INVALID = [(src, dst) for src in S.values for dst in S.values if dst not in ALLOWED[src]]


def make_report(status=S.DRAFT):
    user, _ = BotUser.objects.get_or_create(wa_phone="+237600000001")
    return Report.objects.create(reporter=user, status=status)


def test_graph_matches_the_agreed_edges():
    assert set(VALID) == {
        ("draft", "pending"),
        ("draft", "withdrawn"),
        ("pending", "approved"),
        ("pending", "rejected"),
        ("pending", "needs_info"),
        ("pending", "merged"),
        ("needs_info", "pending"),
        ("needs_info", "rejected"),
        ("needs_info", "withdrawn"),
        ("approved", "rejected"),
        ("approved", "merged"),
        ("rejected", "pending"),
    }


@pytest.mark.parametrize(("src", "dst"), VALID)
def test_valid_edge_changes_status_and_writes_audit(src, dst):
    actor = get_user_model().objects.create_user("mod")
    report = make_report(src)

    report.transition(dst, actor=actor, reason="why")

    report.refresh_from_db()
    assert report.status == dst
    entry = AuditLog.objects.get(action="report.transition")
    assert entry.actor == actor
    assert entry.object_id == str(report.pk)
    assert entry.metadata == {"from_": src, "to": dst, "reason": "why"}


@pytest.mark.parametrize(("src", "dst"), INVALID)
def test_invalid_edge_raises_and_leaves_report_untouched(src, dst):
    report = make_report(src)

    with pytest.raises(InvalidTransition):
        report.transition(dst)

    report.refresh_from_db()
    assert report.status == src
    assert not AuditLog.objects.exists()


def test_actor_may_be_none_for_system_transitions():
    report = make_report()
    report.transition(S.PENDING)
    assert AuditLog.objects.get().actor is None


def test_submitted_at_set_on_first_pending_only():
    report = make_report()
    report.transition(S.PENDING)
    first = report.submitted_at
    assert first is not None
    report.transition(S.NEEDS_INFO)
    report.transition(S.PENDING)
    assert report.submitted_at == first


@pytest.mark.parametrize("dst", [S.APPROVED, S.REJECTED])
def test_decided_at_set_on_decision(dst):
    report = make_report(S.PENDING)
    assert report.decided_at is None
    report.transition(dst)
    assert report.decided_at is not None


def test_merge_into_sets_target_and_status():
    target = make_report(S.APPROVED)
    report = make_report(S.PENDING)

    report.merge_into(target, actor=None)

    report.refresh_from_db()
    assert report.status == S.MERGED
    assert report.merged_into == target
    assert report.decided_at is not None


def test_merge_into_self_rejected():
    report = make_report(S.PENDING)
    with pytest.raises(InvalidTransition):
        report.merge_into(report, actor=None)


@pytest.mark.parametrize("target_status", [S.DRAFT, S.WITHDRAWN, S.REJECTED, S.MERGED])
def test_merge_into_non_live_target_rejected(target_status):
    target = make_report(target_status)
    report = make_report(S.PENDING)
    with pytest.raises(InvalidTransition):
        report.merge_into(target, actor=None)
    report.refresh_from_db()
    assert report.status == S.PENDING
    assert report.merged_into is None


@pytest.mark.parametrize("target_status", [S.PENDING, S.NEEDS_INFO, S.APPROVED])
def test_merge_into_live_target_allowed(target_status):
    target = make_report(target_status)
    report = make_report(S.PENDING)
    report.merge_into(target)
    assert report.status == S.MERGED
    assert report.merged_into == target


def test_stale_copy_cannot_make_invalid_transition():
    report = make_report(S.PENDING)
    stale = Report.objects.get(pk=report.pk)

    report.transition(S.APPROVED)

    with pytest.raises(InvalidTransition):
        stale.transition(S.NEEDS_INFO)  # invalid from the DB state (approved)
    assert Report.objects.get(pk=report.pk).status == S.APPROVED
    assert AuditLog.objects.count() == 1


def test_transition_refreshes_in_memory_instance():
    report = make_report(S.PENDING)
    report.transition(S.APPROVED)
    assert report.decided_at is not None
    assert report.decided_at == Report.objects.get(pk=report.pk).decided_at
