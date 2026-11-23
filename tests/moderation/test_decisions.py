import pytest
from django.urls import reverse

from tchekam.core.models import AuditLog
from tchekam.reports.models import ModerationDecision, Report
from tchekam.reports.tasks import report_decided
from tchekam.reputation.service import band_for_phone

from .conftest import SELLER, post_data, warm

pytestmark = pytest.mark.django_db


def decide_url(report):
    return reverse("moderation:decide", args=[report.pk])


def decide(post, report, action, **fields):
    return post(decide_url(report), post_data(report, action=action, **fields))


def errors(resp):
    return [str(m) for m in resp.wsgi_request._messages if m.level_tag == "error"]


def test_approve_without_confirmed_seller_fails_and_changes_nothing(make_report, post):
    report = make_report()
    before = Report.objects.filter(pk=report.pk).values().get()

    resp = decide(post, report, "approve")

    assert resp.status_code == 302 and resp["Location"].endswith(f"/reports/{report.pk}/")
    assert "confirmed seller" in errors(resp)[-1]
    assert Report.objects.filter(pk=report.pk).values().get() == before
    assert not ModerationDecision.objects.exists()
    assert not AuditLog.objects.filter(action="report.transition").exists()


def test_approve_needs_a_phone_subject_in_seller_role(make_report, post):
    report = make_report(confirmed=True)
    report.subjects.update(role="payee")

    decide(post, report, "approve")

    report.refresh_from_db()
    assert report.status == "pending"


def test_approve_with_confirmed_seller_updates_band_and_records_everything(
    make_report, post, staff
):
    report = make_report(confirmed=True)
    assert warm().band == "yellow"

    resp = decide(post, report, "approve")

    assert resp.status_code == 302 and resp["Location"] == reverse("moderation:queue")
    report.refresh_from_db()
    assert report.status == "approved" and report.decided_at is not None
    d = ModerationDecision.objects.get()
    assert (d.report_id, d.moderator, d.action) == (report.pk, staff, "approve")
    assert band_for_phone(SELLER).band == "orange"
    assert AuditLog.objects.filter(action="report.transition", object_id=str(report.pk)).exists()


def test_approve_with_edits_in_the_same_post_confirms_then_approves(make_report, post):
    report = make_report()
    subject = report.subjects.get()
    assert warm().band == "yellow"

    decide(post, report, "approve", **{f"confirmed_{subject.pk}": "on", "has_payment_proof": "on"})

    report.refresh_from_db()
    assert report.status == "approved" and report.has_payment_proof
    assert band_for_phone(SELLER).band == "red"
    assert AuditLog.objects.filter(action="report.edit").exists()


def test_failed_approve_rolls_back_the_edits_sent_with_it(make_report, post):
    report = make_report()

    decide(post, report, "approve", has_payment_proof="on")

    report.refresh_from_db()
    assert not report.has_payment_proof and report.status == "pending"
    assert not AuditLog.objects.filter(action="report.edit").exists()


def test_double_post_of_approve_creates_one_decision(make_report, post):
    report = make_report(confirmed=True)
    data = post_data(report, action="approve")

    first = post(decide_url(report), data)
    second = post(decide_url(report), data)

    assert first.status_code == 302 and second.status_code == 302
    assert "not allowed" in errors(second)[-1].lower()
    assert ModerationDecision.objects.count() == 1


def test_reject_requires_a_valid_reason_and_text_for_other(make_report, post):
    report = make_report()
    for fields in (
        {},
        {"reason_code": "bogus"},
        {"reason_code": "other"},
        {"reason_code": "other", "reason_text": "   "},
        {"reason_code": "duplicate", "reason_text": "x" * 501},
    ):
        decide(post, report, "reject", **fields)
        report.refresh_from_db()
        assert report.status == "pending", fields
    assert not ModerationDecision.objects.exists()


def test_reject_stores_reason_and_keeps_free_text_out_of_the_audit_log(make_report, post):
    report = make_report(confirmed=True)
    assert warm().band == "yellow"

    decide(post, report, "reject", reason_code="other", reason_text="seller is my cousin 677000111")

    report.refresh_from_db()
    assert report.status == "rejected"
    assert ModerationDecision.objects.get().reason == "other: seller is my cousin 677000111"
    assert all("677000111" not in str(a.metadata) for a in AuditLog.objects.all())
    assert band_for_phone(SELLER).band == "green"


def test_reject_preset_without_text(make_report, post):
    report = make_report()
    decide(post, report, "reject", reason_code="insufficient_evidence")
    assert ModerationDecision.objects.get().reason == "insufficient_evidence"


def test_approved_report_can_be_rejected_and_band_drops(make_report, post):
    report = make_report(status="approved", confirmed=True)
    assert warm().band == "orange"

    decide(post, report, "reject", reason_code="abusive_or_false")

    assert band_for_phone(SELLER).band == "green"


def test_need_info_requires_a_message(make_report, post):
    report = make_report()
    for message in ("", "  ", "x" * 501):
        decide(post, report, "need_info", message=message)
    report.refresh_from_db()
    assert report.status == "pending" and not ModerationDecision.objects.exists()

    decide(post, report, "need_info", message="Please send the MoMo SMS")

    report.refresh_from_db()
    assert report.status == "needs_info"
    assert ModerationDecision.objects.get().reason == "Please send the MoMo SMS"


def test_merge_into_a_live_report(make_report, post):
    report = make_report()
    target = make_report(status="approved", phone="+237677000555")

    resp = decide(post, report, "merge", merge_target=str(target.pk))

    assert resp["Location"] == reverse("moderation:queue")
    report.refresh_from_db()
    assert report.status == "merged" and report.merged_into_id == target.pk
    assert ModerationDecision.objects.get().action == "merge"


@pytest.mark.parametrize("target_status", ["rejected", "merged", "draft", "withdrawn"])
def test_merge_into_a_dead_target_is_refused(make_report, post, target_status):
    report = make_report()
    target = make_report(status=target_status, phone=None)

    resp = decide(post, report, "merge", merge_target=str(target.pk))

    assert "merge target" in errors(resp)[-1]
    report.refresh_from_db()
    assert report.status == "pending" and not ModerationDecision.objects.exists()


def test_merge_into_itself_or_a_missing_report_is_refused(make_report, post):
    report = make_report()
    for target in (str(report.pk), "999999", "", "abc"):
        decide(post, report, "merge", merge_target=target)
    report.refresh_from_db()
    assert report.status == "pending" and not ModerationDecision.objects.exists()


def test_reopen_only_for_rejected_with_a_reason(make_report, post):
    rejected = make_report(status="rejected", phone=None)
    decide(post, rejected, "reopen")  # no reason
    rejected.refresh_from_db()
    assert rejected.status == "rejected"

    decide(post, rejected, "reopen", reopen_reason="new evidence arrived")
    rejected.refresh_from_db()
    assert rejected.status == "pending"
    assert ModerationDecision.objects.get().reason == "new evidence arrived"

    for status in ("needs_info", "approved", "merged"):
        other = make_report(status=status, phone=None)
        resp = decide(post, other, "reopen", reopen_reason="why not")
        assert "not allowed" in errors(resp)[-1].lower(), status
        other.refresh_from_db()
        assert other.status == status


def test_stale_token_refuses_every_decision(make_report, post):
    report = make_report(confirmed=True)
    data = post_data(report, action="approve")
    report.subjects.update(confirmed=False)  # someone else changed it meanwhile

    resp = post(decide_url(report), data)

    assert resp.status_code == 409
    report.refresh_from_db()
    assert report.status == "pending" and not ModerationDecision.objects.exists()


def test_missing_token_is_refused(make_report, post):
    report = make_report(confirmed=True)
    resp = post(decide_url(report), {"action": "approve"})
    assert resp.status_code == 409


def test_unknown_action_is_refused(make_report, post):
    report = make_report(confirmed=True)
    decide(post, report, "delete")
    report.refresh_from_db()
    assert report.status == "pending"


def test_decision_enqueues_notify_after_commit(
    make_report, staff_client, monkeypatch, django_capture_on_commit_callbacks
):
    calls = []
    monkeypatch.setattr(
        "tchekam.moderation.service.enqueue", lambda name, **kw: calls.append((name, kw))
    )
    report = make_report(confirmed=True)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        staff_client.post(decide_url(report), post_data(report, action="approve"))
    assert calls == []  # nothing before commit
    for cb in callbacks:
        cb()

    d = ModerationDecision.objects.get()
    assert calls == [("notify.report_decided", {"report_id": report.pk, "decision_id": d.pk})]


def test_notify_stub_is_registered_and_a_noop():
    from tchekam.core.tasks import enqueue

    enqueue("notify.report_decided", report_id=1, decision_id=2)
    assert report_decided(1, 2) is None


def _transition_audits(report):
    return AuditLog.objects.filter(action="report.transition", object_id=str(report.pk))


@pytest.mark.parametrize(
    ("action", "fields", "start"),
    [
        ("approve", {}, "pending"),
        ("reject", {"reason_code": "duplicate"}, "pending"),
        ("need_info", {"message": "more please"}, "pending"),
        ("reopen", {"reopen_reason": "again"}, "rejected"),
    ],
)
def test_every_decision_writes_a_transition_audit_row(make_report, post, action, fields, start):
    report = make_report(status=start, confirmed=True)

    decide(post, report, action, **fields)

    assert _transition_audits(report).count() == 1


def test_merge_writes_a_transition_audit_row(make_report, post):
    report = make_report(confirmed=True)
    target = make_report(phone="+237677000555")

    decide(post, report, "merge", merge_target=str(target.pk))

    assert _transition_audits(report).count() == 1


def test_merge_invalidates_the_merged_reports_number(make_report, post):
    report = make_report()
    target = make_report(phone="+237677000555")
    assert warm().band == "yellow"

    decide(post, report, "merge", merge_target=str(target.pk))

    assert band_for_phone(SELLER).band == "green"


def test_reopen_invalidates_the_number(make_report, post):
    report = make_report(status="rejected")
    assert warm().band == "green"

    decide(post, report, "reopen", reopen_reason="new evidence")

    assert band_for_phone(SELLER).band == "yellow"


def test_need_info_keeps_the_band_fresh_and_yellow(make_report, post):
    report = make_report()
    assert warm().band == "yellow"

    decide(post, report, "need_info", message="send the SMS")

    from django.core.cache import cache

    from tchekam.reputation.service import cache_key

    assert cache.get(cache_key(SELLER)) is None  # dropped, recomputed on next read
    assert band_for_phone(SELLER).band == "yellow"


def test_approve_cannot_bypass_the_seller_rule_by_removing_the_only_confirmed_seller(
    make_report, post
):
    report = make_report(confirmed=True)
    subject = report.subjects.get()

    decide(post, report, "approve", **{f"remove_{subject.pk}": "on"})

    report.refresh_from_db()
    assert report.status == "pending" and report.subjects.count() == 1
    assert not ModerationDecision.objects.exists()
    assert not AuditLog.objects.filter(action="report.edit").exists()


def test_approve_cannot_bypass_the_seller_rule_by_unchecking_confirmed(make_report, post):
    report = make_report(confirmed=True)
    subject = report.subjects.get()
    data = post_data(report, action="approve")
    del data[f"confirmed_{subject.pk}"]

    post(decide_url(report), data)

    report.refresh_from_db()
    assert report.status == "pending"
    assert report.subjects.get().confirmed is True
    assert not ModerationDecision.objects.exists()
    assert not AuditLog.objects.filter(action="report.edit").exists()
