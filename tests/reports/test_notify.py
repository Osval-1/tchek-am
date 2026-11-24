"""Issue 15: reporter notifications, the 24 h rule and the need-more-info loop. All fakes."""

import logging
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase
from django.utils import timezone

from tchekam.core.audit import AuditLog
from tchekam.i18n import t
from tchekam.identifiers.models import get_or_create_phone
from tchekam.messaging.channel import ChannelError
from tchekam.moderation import service as moderation
from tchekam.reports import flow, tasks
from tchekam.reports.models import (
    Evidence,
    ModerationDecision,
    PendingNotification,
    Report,
    ReportSubject,
)
from tchekam.reports.tasks import report_decided
from tchekam.reputation.facts import Band
from tchekam.reputation.service import band_for_phone, cache_key

from .conftest import png

pytestmark = pytest.mark.django_db

EN = "en"
SELLER = "+237677123456"
REF = "TA-00042"
BANNED = ("scammer", "fraudster", "fraud")


@pytest.fixture(autouse=True)
def _clean_cache():
    from django.core.cache import cache

    cache.clear()


@pytest.fixture
def mod(db):
    return get_user_model().objects.create_user("mod", password="x", is_staff=True)


@pytest.fixture
def recent(bot):
    """The reporter wrote a minute ago, so the 24 h window is open."""
    bot.user.last_inbound_at = timezone.now() - timedelta(minutes=1)
    bot.user.save()
    return bot


def _report(bot, status="pending", reference=REF, **kw) -> Report:
    report = Report.objects.create(
        reporter=bot.user, status=status, reference=reference, submitted_at=timezone.now(), **kw
    )
    ReportSubject.objects.create(
        report=report,
        phone_number=get_or_create_phone(SELLER),
        role="seller",
        source="ai",
        confirmed=True,
    )
    return report


def _decision(report, mod, action, reason="") -> ModerationDecision:
    return ModerationDecision.objects.create(
        report=report, moderator=mod, action=action, reason=reason
    )


def _notify(bot, report, mod, action, reason="") -> list[str]:
    decision = _decision(report, mod, action, reason)
    bot.channel.sent.clear()
    report_decided(report.pk, decision.pk)
    return [m["text"] for m in bot.channel.sent]


def _set_lang(bot, lang):
    bot.user.language = lang
    bot.user.save()


# Messages per decision ------------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_approve_message_and_next_steps(recent, mod, lang):
    _set_lang(recent, lang)
    report = _report(recent, status="approved")

    (text,) = _notify(recent, report, mod, "approve")

    assert t("notify.approved", lang, reference=REF) in text
    assert t("notify.next_steps", lang) in text
    assert text.index(t("notify.next_steps", lang)) > text.index(REF)


@pytest.mark.parametrize("lang", ["fr", "en"])
@pytest.mark.parametrize(
    ("reason", "key"),
    [
        ("insufficient_evidence", "notify.rejected.insufficient_evidence"),
        ("duplicate", "notify.rejected.duplicate"),
        ("cannot_verify", "notify.rejected.cannot_verify"),
        ("not_a_scam", "notify.rejected.generic"),
        ("abusive_or_false", "notify.rejected.generic"),
        ("other: free text", "notify.rejected.generic"),
        ("garbage", "notify.rejected.generic"),
    ],
)
def test_reject_messages_per_category(recent, mod, lang, reason, key):
    _set_lang(recent, lang)
    report = _report(recent, status="rejected")

    (text,) = _notify(recent, report, mod, "reject", reason)

    assert t(key, lang, reference=REF) in text
    assert t("notify.next_steps", lang) in text


def test_reject_never_forwards_the_moderators_free_text(recent, mod):
    report = _report(recent, status="rejected")

    (text,) = _notify(recent, report, mod, "reject", "other: MODNOTE-XYZ you lied")

    assert "MODNOTE" not in text and "lied" not in text
    assert not any(w in text.lower() for w in BANNED)


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_need_info_quotes_the_question_without_next_steps(recent, mod, lang):
    _set_lang(recent, lang)
    report = _report(recent, status="needs_info")

    (text,) = _notify(recent, report, mod, "need_info", "Which number did you pay?")

    assert "> Which number did you pay?" in text
    assert t("notify.need_info.reply", lang) in text
    assert t("notify.next_steps", lang) not in text


def test_need_info_question_is_plain_text_and_capped(recent, mod):
    report = _report(recent, status="needs_info")
    nasty = "*bold* _it_ ~x~ `c`\x1b\x07 line1\n\n\nline2\r\n" + "z" * 800

    (text,) = _notify(recent, report, mod, "need_info", nasty)

    quoted = [ln for ln in text.splitlines() if ln.startswith("> ")]
    assert quoted[0] == "> bold it x c line1"
    assert quoted[1] == "> line2"
    assert sum(len(ln) - 2 for ln in quoted) <= 500
    assert "\x1b" not in text and "\x07" not in text and "*" not in text


def test_merge_into_approved_reads_as_approved(recent, mod):
    target = _report(recent, status="approved", reference="TA-00001")
    report = _report(recent, status="merged", merged_into=target)

    (text,) = _notify(recent, report, mod, "merge", "merged into 1")

    assert t("notify.approved", "en", reference=REF) in text
    assert t("notify.next_steps", "en") in text


def test_merge_into_pending_reads_as_linked(recent, mod):
    target = _report(recent, status="pending", reference="TA-00001")
    report = _report(recent, status="merged", merged_into=target)

    (text,) = _notify(recent, report, mod, "merge", "merged into 1")

    assert t("notify.merged_pending", "en", reference=REF) in text
    assert t("notify.next_steps", "en") not in text


def test_reopen_message(recent, mod):
    report = _report(recent)

    (text,) = _notify(recent, report, mod, "reopen", "new evidence")

    assert t("notify.reopened", "en", reference=REF) in text
    assert "new evidence" not in text
    assert t("notify.next_steps", "en") not in text


def test_help_url_is_appended_when_set(recent, mod, settings):
    report = _report(recent, status="approved")
    settings.HELP_URL = "https://help.test/x"
    (with_url,) = _notify(recent, report, mod, "approve")
    settings.HELP_URL = ""
    (without,) = _notify(recent, report, mod, "approve")

    assert t("notify.more_help", "en", url="https://help.test/x") in with_url
    assert "More help" not in without


def test_messages_go_to_the_reporter_only(recent, mod):
    report = _report(recent, status="approved")
    _notify(recent, report, mod, "approve")

    assert [m["to"] for m in recent.channel.sent] == ["237670000055"]


# Silence and the 24 h rule --------------------------------------------------------------------


def test_blocked_reporter_gets_nothing_and_nothing_is_queued(recent, mod):
    recent.user.blocked = True
    recent.user.save()
    report = _report(recent, status="approved")

    assert _notify(recent, report, mod, "approve") == []
    assert not PendingNotification.objects.exists()


def test_erased_reporter_is_skipped(recent, mod):
    report = _report(recent, status="approved")
    decision = _decision(report, mod, "approve")
    Report.objects.filter(pk=report.pk).update(reporter=None)

    report_decided(report.pk, decision.pk)

    assert recent.channel.sent == []
    assert not PendingNotification.objects.exists()


def test_unknown_decision_is_a_noop():
    assert report_decided(999, 999) is None


def test_after_24h_it_is_queued_and_nothing_is_sent(bot, mod):
    bot.user.last_inbound_at = timezone.now() - timedelta(hours=25)
    bot.user.save()
    report = _report(bot, status="approved")

    assert _notify(bot, report, mod, "approve") == []

    pending = PendingNotification.objects.get()
    assert pending.user == bot.user and pending.report == report
    assert pending.delivered_at is None


def test_never_messaged_user_is_queued(bot, mod):
    report = _report(bot, status="approved")
    assert _notify(bot, report, mod, "approve") == []
    assert PendingNotification.objects.count() == 1


def test_window_is_configurable(recent, mod, settings):
    settings.REPLY_WINDOW_HOURS = 0
    report = _report(recent, status="approved")

    assert _notify(recent, report, mod, "approve") == []
    assert PendingNotification.objects.count() == 1


def test_double_run_sends_once(recent, mod):
    report = _report(recent, status="approved")
    decision = _decision(report, mod, "approve")

    report_decided(report.pk, decision.pk)
    report_decided(report.pk, decision.pk)

    assert len(recent.channel.sent) == 1
    decision.refresh_from_db()
    assert decision.notified_at is not None


def test_double_run_queues_once(bot, mod):
    report = _report(bot, status="approved")
    decision = _decision(report, mod, "approve")

    report_decided(report.pk, decision.pk)
    report_decided(report.pk, decision.pk)

    assert PendingNotification.objects.count() == 1


def test_send_failure_is_queued_for_the_next_message(recent, mod, monkeypatch):
    report = _report(recent, status="approved")

    def boom(to, text):
        raise ChannelError("down")

    monkeypatch.setattr(recent.channel, "send_text", boom)

    assert _notify(recent, report, mod, "approve") == []
    assert PendingNotification.objects.filter(delivered_at__isnull=True).count() == 1


# Delivery on the next message -----------------------------------------------------------------


def _queue(bot, mod, n=1, action="approve", status="approved"):
    bot.user.last_inbound_at = timezone.now() - timedelta(hours=30)
    bot.user.save()
    ids = []
    for i in range(n):
        report = _report(bot, status=status, reference=f"TA-0010{i}")
        decision = _decision(report, mod, action, "Need the number")
        report_decided(report.pk, decision.pk)
        ids.append(report.pk)
    assert bot.channel.sent == []
    return ids


def test_pending_is_delivered_once_before_the_menu(bot, mod):
    _queue(bot, mod)

    texts = bot.text("menu")

    assert t("notify.approved", "en", reference="TA-00100") in texts[0]
    assert texts[-1].startswith(t("menu.main", "en"))
    assert len(texts) == 2
    assert PendingNotification.objects.get().delivered_at is not None
    assert len(bot.text("menu")) == 1  # not again


def test_at_most_three_per_message(bot, mod):
    _queue(bot, mod, n=4)

    first = bot.text("menu")
    second = bot.text("menu")

    assert len(first) == 4 and len(second) == 2
    assert first[0].count("TA-00100") == 1 and "TA-00103" in second[0]


def test_blocked_user_gets_no_delivery(bot, mod):
    _queue(bot, mod)
    bot.user.blocked = True
    bot.user.save()

    assert bot.text("menu") == []
    assert PendingNotification.objects.get().delivered_at is None


def test_need_info_delivered_while_idle_enters_the_needs_info_flow(bot, mod):
    (rid,) = _queue(bot, mod, action="need_info", status="needs_info")

    bot.text("hello there")  # not a command: routed to a message check, conversation idle

    conv = bot.conversation
    assert conv.flow == flow.NEEDS_INFO
    assert conv.state["report_id"] == rid


def test_need_info_delivered_inside_another_flow_leaves_it(bot, mod):
    _queue(bot, mod, action="need_info", status="needs_info")
    conv = bot.conversation
    conv.flow = "await_number"
    conv.save()

    texts = bot.text("hello")  # await_number keeps waiting for a number

    assert "Need the number" in texts[0]
    assert bot.conversation.flow == "await_number"


def test_stale_need_info_is_dropped_silently(bot, mod):
    (rid,) = _queue(bot, mod, action="need_info", status="needs_info")
    Report.objects.filter(pk=rid).update(status="rejected")  # decided again in the meantime

    texts = bot.text("menu")

    assert len(texts) == 1
    assert PendingNotification.objects.get().delivered_at is not None


# Needs-info loop ------------------------------------------------------------------------------


def _ask(bot, mod, question="Please send the payment SMS"):
    """A pending report that the moderator sends back through the real moderation service."""
    bot.user.last_inbound_at = timezone.now()
    bot.user.save()
    report = _report(bot)
    return report, _moderate(report, mod, "need_info", message=question)


def _idle(bot):
    conv = bot.conversation
    conv.reset()
    conv.save()


def _moderate(report, mod, action, **fields):
    row = Report.objects.get(pk=report.pk)
    data = QueryDict(mutable=True)
    data.update({"action": action, "state_token": moderation.state_token(row), **fields})
    with TestCase.captureOnCommitCallbacks(execute=True):  # run the notify enqueue
        return moderation.decide(report.pk, mod, data)


def test_round_trip_need_info_image_done_back_to_pending(bot, mod):
    report, _ = _ask(bot, mod)
    report.refresh_from_db()
    assert report.status == "needs_info"
    assert any("Please send the payment SMS" in m.get("text", "") for m in bot.channel.sent)
    band_for_phone(SELLER)  # warm the cache: the status change must invalidate it
    assert cache.get(cache_key(SELLER)) is not None

    assert bot.conversation.flow == flow.NEEDS_INFO  # started by the notification itself
    bot.image(png("blue"))
    bot.text("The seller also wrote me from another phone")
    assert Evidence.objects.filter(report=report).count() == 1
    with TestCase.captureOnCommitCallbacks(execute=True):  # the status signal runs on commit
        done = bot.text("DONE")

    report.refresh_from_db()
    assert report.status == "pending"
    assert done == [t("report.needs_info.resubmitted", EN, reference=REF)]
    assert bot.conversation.flow == "idle"
    assert "another phone" in report.story_text
    assert AuditLog.objects.filter(
        action="report.transition", object_id=str(report.pk), metadata__to="pending"
    ).exists()
    assert cache.get(cache_key(SELLER)) is None
    assert band_for_phone(SELLER).band == Band.YELLOW


def test_done_without_new_content_asks_again(bot, mod):
    report, _ = _ask(bot, mod)

    assert bot.text("DONE") == [t("report.needs_info.need_content", EN)]
    report.refresh_from_db()
    assert report.status == "needs_info"
    assert bot.conversation.flow == flow.NEEDS_INFO


def test_old_evidence_does_not_count_as_new(bot, mod):
    report, _ = _ask(bot, mod)
    Evidence.objects.create(
        report=report, object_key="k-old", mimetype="image/png", sha256="0" * 64, size_bytes=1
    )
    Evidence.objects.filter(report=report).update(created_at=timezone.now() - timedelta(days=1))

    assert bot.text("1") == [t("report.needs_info.need_content", EN)]


def test_text_alone_is_enough_and_finish_words_work(bot, mod):
    report, _ = _ask(bot, mod)
    bot.text("The number was 677 123 456")

    assert bot.text("fini")[0].startswith("Thanks")
    report.refresh_from_db()
    assert report.status == "pending"


def test_cancel_keeps_needs_info(bot, mod):
    report, _ = _ask(bot, mod)

    assert bot.text("CANCEL") == [t("report.needs_info.cancelled", EN)]

    report.refresh_from_db()
    assert report.status == "needs_info"
    assert bot.conversation.flow == "idle"


def test_report_intent_resumes_without_new_draft_or_limit(bot, mod, settings):
    settings.REPORTS_PER_DAY = 1
    report, _ = _ask(bot, mod)  # submitted today: the daily limit is already used up
    _idle(bot)

    texts = bot.text("4")

    assert "Please send the payment SMS" in texts[0]
    assert bot.conversation.flow == flow.NEEDS_INFO
    assert not Report.objects.filter(status="draft").exists()
    assert Report.objects.filter(reporter=bot.user).count() == 1


def test_first_image_of_report_intent_is_added_to_the_needs_info_report(bot, mod):
    report, _ = _ask(bot, mod)
    _idle(bot)
    bot.image(png("green"))  # idle: asks what to do with the image
    bot.text("2")  # "report it"

    assert Evidence.objects.filter(report=report).count() == 1
    assert bot.conversation.flow == flow.NEEDS_INFO


def test_flow_with_a_report_that_moved_on_resets(bot, mod):
    report, _ = _ask(bot, mod)
    Report.objects.filter(pk=report.pk).update(status="rejected")

    texts = bot.text("DONE")

    assert texts == [t("report.needs_info.not_waiting", EN)]
    assert bot.conversation.flow == "idle"


def test_items_limit_counts_all_evidence(bot, mod):
    report, _ = _ask(bot, mod)
    for i in range(9):
        Evidence.objects.create(
            report=report, object_key=f"k-{i}", mimetype="image/png", sha256="1" * 64, size_bytes=1
        )
    bot.image(png("red", 9))

    assert bot.image(png("red", 10)) == [t("report.limit_items", EN)]
    assert Evidence.objects.filter(report=report).count() == 10


def test_size_limit_counts_all_evidence(bot, mod, monkeypatch):
    monkeypatch.setattr(tasks, "MAX_TOTAL_BYTES", 1000)
    report, _ = _ask(bot, mod)
    Evidence.objects.create(
        report=report, object_key="k-big", mimetype="image/png", sha256="2" * 64, size_bytes=900
    )

    assert bot.image(b"x" * 200) == [t("report.limit_size", EN)]


@pytest.mark.parametrize("status", ["withdrawn", "rejected", "pending", "approved"])
def test_ingest_refuses_other_statuses_but_accepts_needs_info(bot, mod, status):
    report, _ = _ask(bot, mod)
    bot.image(png("blue"))
    message_id = bot.last_id
    assert Evidence.objects.filter(report=report).count() == 1

    Evidence.objects.filter(report=report).delete()
    Report.objects.filter(pk=report.pk).update(status=status)
    tasks.ingest_media(report_id=report.pk, message_id=message_id, kind="image")
    assert Evidence.objects.filter(report=report).count() == 0

    Report.objects.filter(pk=report.pk).update(status="needs_info")
    tasks.ingest_media(report_id=report.pk, message_id=message_id, kind="image")
    assert Evidence.objects.filter(report=report).count() == 1


# Privacy --------------------------------------------------------------------------------------


def test_nothing_personal_is_logged(recent, mod, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    report = _report(recent, status="needs_info", story_text="STORYSECRET")

    def boom(to, text):
        raise ChannelError("body had MODSECRET")

    monkeypatch.setattr(recent.channel, "send_text", boom)
    _notify(recent, report, mod, "need_info", "MODSECRET question 677123456")

    logged = caplog.text
    assert "MODSECRET" not in logged and "STORYSECRET" not in logged
    assert "677123456" not in logged and "237670000055" not in logged


def test_settings_defaults():
    assert settings.REPLY_WINDOW_HOURS == 24
    assert hasattr(settings, "HELP_URL")


# Direct send starts the loop; busy users are told how --------------------------------------------


def test_direct_need_info_starts_the_loop_so_a_text_reply_is_not_a_check(bot, mod):
    report, _ = _ask(bot, mod)

    assert bot.text("It was 25000 FCFA")[0] == t("report.story_noted", EN)
    assert report.__class__.objects.get(pk=report.pk).story_text == "It was 25000 FCFA"


def test_direct_need_info_in_a_busy_conversation_says_to_type_4(bot, mod):
    bot.user.last_inbound_at = timezone.now()
    bot.user.save()
    conv = bot.conversation
    conv.flow = "await_number"
    conv.save()
    report = _report(bot, status="needs_info")

    (text,) = _notify(bot, report, mod, "need_info", "Which number?")

    assert t("notify.need_info.reply_busy", EN) in text
    assert t("notify.need_info.reply", EN) not in text
    assert bot.conversation.flow == "await_number"


def test_direct_need_info_with_a_stale_prompt_starts_the_loop(bot, mod):
    bot.user.last_inbound_at = timezone.now()
    bot.user.save()
    conv = bot.conversation
    conv.flow, conv.expires_at = "await_number", timezone.now() - timedelta(minutes=1)
    conv.save()
    report = _report(bot, status="needs_info")

    (text,) = _notify(bot, report, mod, "need_info", "Which number?")

    assert t("notify.need_info.reply", EN) in text
    assert bot.conversation.flow == flow.NEEDS_INFO


def test_queued_need_info_in_a_busy_conversation_says_to_type_4(bot, mod):
    _queue(bot, mod, action="need_info", status="needs_info")
    conv = bot.conversation
    conv.flow = "await_number"
    conv.save()

    texts = bot.text("hello")

    assert t("notify.need_info.reply_busy", EN) in texts[0]


def test_empty_question_falls_back_to_a_generic_ask(recent, mod):
    report = _report(recent, status="needs_info")

    (text,) = _notify(recent, report, mod, "need_info", "***  ~~")

    assert f"> {t('notify.need_info.generic_question', EN)}" in text


def test_new_text_counts_when_the_story_is_nearly_full(bot, mod):
    report, _ = _ask(bot, mod)
    Report.objects.filter(pk=report.pk).update(story_text="a" * (flow.MAX_STORY - 1))
    _idle(bot)
    bot.text("4")  # re-enter so the baseline is the long story

    bot.text("more details")  # only one character fits, which is still new content

    assert bot.text("DONE")[0].startswith("Thanks")


# Delivery failure keeps queued notifications -------------------------------------------------


def test_failed_delivery_keeps_the_notification_pending(bot, mod, monkeypatch):
    _queue(bot, mod)

    def boom(to, text):
        raise ChannelError("down")

    monkeypatch.setattr(bot.channel, "send_text", boom)
    bot.text("menu")  # delivery raises; the pipeline records the failure

    assert PendingNotification.objects.get().delivered_at is None
    monkeypatch.undo()
    texts = bot.text("menu")
    assert t("notify.approved", EN, reference="TA-00100") in texts[0]
    assert PendingNotification.objects.get().delivered_at is not None


def test_failed_delivery_does_not_start_the_loop(bot, mod, monkeypatch):
    (rid,) = _queue(bot, mod, action="need_info", status="needs_info")
    story = Report.objects.get(pk=rid).story_text

    def boom(to, text):
        raise ChannelError("down")

    monkeypatch.setattr(bot.channel, "send_text", boom)
    bot.text("menu")
    assert bot.conversation.flow == "idle"
    monkeypatch.undo()

    texts = bot.text("677123456")  # a number check, not an answer to an unseen question

    assert len(texts) == 2  # the question, then the number check's answer
    assert bot.conversation.flow == flow.NEEDS_INFO  # the question was delivered with this reply
    assert t("notify.need_info.reply", EN) in texts[0]
    assert Report.objects.get(pk=rid).story_text == story


def test_following_the_busy_copy_reaches_the_needs_info_loop(bot, mod):
    bot.user.last_inbound_at = timezone.now()
    bot.user.save()
    conv = bot.conversation
    conv.flow = "await_number"
    conv.save()
    report = _report(bot, status="needs_info")
    _notify(bot, report, mod, "need_info", "Which number?")

    bot.text("MENU")
    texts = bot.text("4")

    assert bot.conversation.flow == flow.NEEDS_INFO
    assert "Which number?" in texts[0]


def test_direct_need_info_for_a_report_that_moved_on_is_not_sent(recent, mod):
    report = _report(recent, status="rejected")

    assert _notify(recent, report, mod, "need_info", "Which number?") == []
    assert not PendingNotification.objects.exists()
    assert recent.conversation.flow == "idle"
