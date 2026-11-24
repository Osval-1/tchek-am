"""Appeal decisions: band effects, audit, cache invalidation, notification."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from tchekam.appeals import service
from tchekam.appeals.models import Appeal
from tchekam.conversations.models import BotUser, Conversation
from tchekam.core.audit import AuditLog
from tchekam.i18n import t
from tchekam.identifiers.models import get_or_create_phone
from tchekam.reports.models import ModerationDecision, Report
from tchekam.reputation.facts import Band
from tchekam.reputation.service import band_for_phone, cache_key

from .conftest import OWN, months_ago

pytestmark = pytest.mark.django_db
EN = "en"


@pytest.fixture
def user(bot):
    return bot.user


def open_appeal(user, kind="wrong", acquired=None):
    return Appeal.objects.create(
        phone_number=get_or_create_phone(OWN),
        appellant=user,
        kind=kind,
        number_acquired_at=acquired,
        statement="s",
        status="open",
        submitted_at=timezone.now(),
    )


def warm():
    result = band_for_phone(OWN)
    assert cache.get(cache_key(OWN)) is not None
    return result


@pytest.fixture
def commit(django_capture_on_commit_callbacks):
    def run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return run


def test_new_to_me_approval_drops_red_and_later_report_still_counts(
    user, staff, make_report, commit
):
    acquired = months_ago(2)
    make_report(incident=acquired - timedelta(days=30))
    appeal = open_appeal(user, "new_to_me", acquired)
    assert warm().band == Band.RED and warm().under_appeal

    commit(service.decide, appeal.pk, staff, "approve")

    after = band_for_phone(OWN)  # served fresh: the warm entry was invalidated
    assert after.band == Band.GREEN and not after.under_appeal
    make_report(incident=acquired + timedelta(days=3))
    cache.clear()
    assert band_for_phone(OWN).band == Band.RED


def test_acquired_month_boundary_counts_from_the_first_day(user, staff, make_report, commit):
    acquired = months_ago(3)
    before = make_report(incident=acquired - timedelta(days=1))
    appeal = open_appeal(user, "new_to_me", acquired)
    commit(service.decide, appeal.pk, staff, "approve")
    assert band_for_phone(OWN).band == Band.GREEN
    assert before.pk not in band_for_phone(OWN).counted_report_ids
    same_month = make_report(incident=acquired)  # the first day of the month counts
    cache.clear()
    assert same_month.pk in band_for_phone(OWN).counted_report_ids


def test_open_new_to_me_appeal_does_not_exclude_anything_yet(user, make_report):
    make_report(incident=months_ago(5))
    open_appeal(user, "new_to_me", months_ago(2))
    result = band_for_phone(OWN)
    assert result.band == Band.RED and result.under_appeal


def test_rejection_keeps_reports_and_clears_under_appeal(user, staff, make_report, commit):
    make_report(incident=months_ago(5))
    appeal = open_appeal(user, "new_to_me", months_ago(2))
    assert warm().under_appeal
    commit(service.decide, appeal.pk, staff, "reject", reason="no proof")
    after = band_for_phone(OWN)
    assert after.band == Band.RED and not after.under_appeal
    appeal.refresh_from_db()
    assert (appeal.status, appeal.decided_by, appeal.reason) == ("rejected", staff, "no proof")
    assert appeal.decided_at is not None


def test_wrong_approval_rejects_selected_reports_through_transitions(
    user, staff, make_report, commit
):
    keep = make_report(incident=months_ago(5), proof=False)
    drop = make_report(incident=months_ago(5))
    appeal = open_appeal(user)
    assert warm().band == Band.RED
    result = commit(service.decide, appeal.pk, staff, "approve", report_ids=[drop.pk])
    assert result.rejected_reports == [drop.pk]
    drop.refresh_from_db()
    keep.refresh_from_db()
    assert (drop.status, keep.status) == ("rejected", "approved")
    assert AuditLog.objects.filter(
        action="report.transition", object_id=str(drop.pk), metadata__reason="appeal"
    ).exists()
    assert ModerationDecision.objects.filter(report=drop, reason="appeal", moderator=staff).exists()
    assert band_for_phone(OWN).band == Band.ORANGE


def test_wrong_approval_needs_at_least_one_valid_report(user, staff, make_report):
    approved = make_report(incident=months_ago(5))
    pending = make_report(incident=months_ago(5), status="rejected")
    elsewhere = make_report(incident=months_ago(5), phone="+237699123456")
    appeal = open_appeal(user)
    for ids in ([], [pending.pk], [elsewhere.pk], [approved.pk, elsewhere.pk]):
        with pytest.raises(service.AppealError):
            service.decide(appeal.pk, staff, "approve", report_ids=ids)
    appeal.refresh_from_db()
    approved.refresh_from_db()
    assert appeal.status == "open" and approved.status == "approved"


def test_reject_needs_a_reason_and_unknown_action_is_refused(user, staff):
    appeal = open_appeal(user)
    with pytest.raises(service.AppealError):
        service.decide(appeal.pk, staff, "reject", reason="  ")
    with pytest.raises(service.AppealError):
        service.decide(appeal.pk, staff, "maybe")


def test_second_decision_is_refused(user, staff, make_report):
    make_report(incident=months_ago(5))
    appeal = open_appeal(user, "new_to_me", months_ago(2))
    service.decide(appeal.pk, staff, "approve")
    with pytest.raises(service.AppealError, match="already been decided"):
        service.decide(appeal.pk, staff, "reject", reason="x")
    assert AuditLog.objects.filter(action__startswith="appeal.").count() == 1


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_every_decision_is_audited_without_statement(user, staff, action):
    appeal = open_appeal(user, "new_to_me", months_ago(2))
    service.decide(appeal.pk, staff, action, reason="because", ip="10.0.0.1")
    entry = AuditLog.objects.get(action=f"appeal.{action}")
    assert (entry.actor, entry.object_id, entry.ip) == (staff, str(appeal.pk), "10.0.0.1")
    assert "s" not in entry.metadata.values() and "because" not in str(entry.metadata)


def test_submit_invalidates_cache_and_is_atomic(user, make_report, commit):
    make_report(incident=months_ago(5))
    draft = Appeal.objects.create(
        phone_number=get_or_create_phone(OWN), appellant=user, kind="wrong"
    )
    assert not warm().under_appeal
    assert commit(service.submit, draft) is None
    assert band_for_phone(OWN).under_appeal
    assert service.submit(draft) is not None  # already open: not submitted twice


def test_latest_approved_acquisition_date_wins(user, staff, make_report):
    phone = get_or_create_phone(OWN)
    for months in (4, 2):
        Appeal.objects.create(
            phone_number=phone, appellant=None, kind="new_to_me", status="approved",
            number_acquired_at=months_ago(months),
        )  # fmt: skip
    from tchekam.appeals.provider import appeal_state

    assert appeal_state(OWN).number_acquired_at == months_ago(2)


# Notification ---------------------------------------------------------------------------------


def decide_and_notify(user, staff, action="approve", **kw):
    appeal = open_appeal(user, "new_to_me", months_ago(2))
    service.decide(appeal.pk, staff, action, **({"reason": "r"} | kw))
    return appeal


@pytest.fixture
def notify_task(commit):
    from tchekam.appeals.tasks import notify_decided

    return notify_decided


def test_notified_immediately_inside_the_window(user, staff, fake_channel, notify_task):
    user.last_inbound_at = timezone.now() - timedelta(hours=1)
    user.save()
    appeal = decide_and_notify(user, staff)
    notify_task(appeal.pk)
    notify_task(appeal.pk)  # idempotent
    assert [m["text"] for m in fake_channel.sent] == [t("appeal.notify.approved", EN)]
    appeal.refresh_from_db()
    assert appeal.notified_at and appeal.delivered_at


def test_rejection_message_is_neutral_and_points_to_follow_up(
    user, staff, fake_channel, notify_task, settings
):
    settings.HELP_URL = "https://help.example/x"
    user.last_inbound_at = timezone.now()
    user.save()
    appeal = decide_and_notify(user, staff, "reject", reason="secret moderator words")
    notify_task(appeal.pk)
    text = fake_channel.sent[0]["text"]
    assert "APPEAL" in text and "https://help.example/x" in text
    assert "secret moderator words" not in text
    assert not any(w in text.lower() for w in ("scammer", "fraud"))


def test_outside_the_window_it_is_queued_then_delivered_before_next_reply(
    bot, staff, fake_channel, notify_task
):
    BotUser.objects.filter(pk=bot.user.pk).update(
        last_inbound_at=timezone.now() - timedelta(hours=30)
    )
    bot.user.refresh_from_db()
    appeal = decide_and_notify(bot.user, staff)
    notify_task(appeal.pk)
    assert fake_channel.sent == []
    appeal.refresh_from_db()
    assert appeal.notified_at and appeal.delivered_at is None
    texts = bot.text("menu")
    assert texts[0] == t("appeal.notify.approved", EN)
    appeal.refresh_from_db()
    assert appeal.delivered_at
    assert t("appeal.notify.approved", EN) not in bot.text("menu")


def test_failed_send_is_queued(user, staff, fake_channel, notify_task, monkeypatch):
    from tchekam.appeals import notify

    user.last_inbound_at = timezone.now()
    user.save()
    monkeypatch.setattr(notify, "send_to_user", lambda *a, **k: False)
    appeal = decide_and_notify(user, staff)
    notify_task(appeal.pk)
    appeal.refresh_from_db()
    assert appeal.notified_at and appeal.delivered_at is None


def test_blocked_or_erased_appellant_gets_nothing(user, staff, fake_channel, notify_task):
    appeal = decide_and_notify(user, staff)
    Appeal.objects.filter(pk=appeal.pk).update(appellant=None)
    notify_task(appeal.pk)
    notify_task(999999)
    BotUser.objects.filter(pk=user.pk).update(blocked=True)
    assert fake_channel.sent == []


def test_undecided_appeal_is_not_notified(user, fake_channel, notify_task):
    appeal = open_appeal(user)
    notify_task(appeal.pk)
    assert fake_channel.sent == [] and Conversation.objects.filter(user=user).exists()
    assert Report.objects.count() == 0


# Yellow numbers, reporter wording, concurrent rejection ---------------------------------------


def test_wrong_appeal_on_a_yellow_number_can_be_approved_and_goes_green(
    user, staff, make_report, commit
):
    pending = make_report(incident=months_ago(1), status="pending", proof=False)
    appeal = open_appeal(user)
    assert warm().band == Band.YELLOW
    commit(service.decide, appeal.pk, staff, "approve", report_ids=[pending.pk])
    pending.refresh_from_db()
    assert pending.status == "rejected"
    assert band_for_phone(OWN).band == Band.GREEN  # served fresh: the warm entry is gone


def test_reporter_of_an_appeal_rejected_report_gets_neutral_copy(user, staff, make_report):
    from tchekam.reports.notify import render

    report = make_report(incident=months_ago(5))
    appeal = open_appeal(user)
    service.decide(appeal.pk, staff, "approve", report_ids=[report.pk])
    decision = ModerationDecision.objects.get(report=report)
    for lang in ("fr", "en", "pcm"):
        text = render(decision, lang)
        assert t("notify.rejected.after_review", lang, reference=report.reference) in text
        assert t("notify.rejected.generic", lang, reference=report.reference) not in text
        assert not any(w in text.lower() for w in ("appeal", "contest", "scam", "fraud", "arnaque"))


def test_concurrent_rejection_gives_a_friendly_error(user, staff, make_report, monkeypatch):
    report = make_report(incident=months_ago(5))
    appeal = open_appeal(user)
    original = Report.transition

    def lost_race(self, to, actor=None, reason=""):
        Report.objects.filter(pk=self.pk).update(status="rejected")  # someone else got there first
        return original(self, to, actor=actor, reason=reason)

    monkeypatch.setattr(Report, "transition", lost_race)
    with pytest.raises(service.AppealError, match="changed in the meantime"):
        service.decide(appeal.pk, staff, "approve", report_ids=[report.pk])
    appeal.refresh_from_db()
    assert appeal.status == "open"
