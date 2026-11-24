"""Appeal flow end to end through the webhook pipeline (all fakes)."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from tchekam.appeals.models import Appeal, AppealEvidence
from tchekam.conversations.models import BotUser
from tchekam.core.audit import AuditLog
from tchekam.i18n import t
from tchekam.reputation.facts import Band
from tchekam.reputation.service import band_for_phone, cache_key

from ..reports.conftest import png
from .conftest import OWN, months_ago

pytestmark = pytest.mark.django_db
EN = "en"
BANNED = ("scammer", "fraud", "arnaque", "escroc")


def says(texts, key, **fmt):
    return t(key, EN, **fmt) in texts


@pytest.fixture
def reported(make_report):
    return make_report(incident=months_ago(4))


def start(bot, word="APPEAL"):
    texts = bot.text(word)
    assert says(texts, "appeal.choose_kind"), texts


@pytest.mark.parametrize("word", ["APPEAL", "contester", "Contest", "6"])
def test_keywords_and_menu_six_start_the_flow(bot, reported, word):
    start(bot, word)
    assert bot.conversation.flow == "appeal"


def test_nothing_to_appeal_without_reports(bot):
    assert says(bot.text("APPEAL"), "appeal.nothing")
    assert not Appeal.objects.exists()


def test_rejected_only_reports_leave_nothing_to_appeal(bot, make_report):
    make_report(incident=months_ago(4), status="rejected")
    assert says(bot.text("APPEAL"), "appeal.nothing")


@pytest.mark.parametrize(
    "typed",
    ["APPEAL 699123456", "contester +237 699 12 34 56", "Contest winner call 699123456"],
)
def test_another_number_with_the_keyword_is_a_plain_number_check(bot, make_report, typed):
    make_report(incident=months_ago(4), phone="+237699123456")
    make_report(incident=months_ago(4))
    texts = bot.text(typed)
    assert not says(texts, "appeal.choose_kind")
    assert any("699 12 34 56" in x or "699123456" in x for x in texts)  # the other number's check
    assert bot.conversation.flow == "idle"
    assert not Appeal.objects.exists()


def test_flow_itself_refuses_a_different_typed_number(bot, reported):
    from tchekam.appeals import flow
    from tchekam.conversations.router import Context

    ctx = Context(user=bot.user, conversation=bot.conversation, msg=None)
    ctx.extra["typed_numbers"] = ["+237699123456"]
    assert flow.start(ctx)[0].text == t("appeal.own_number_only", EN)


def test_typed_own_number_is_accepted(bot, reported):
    assert says(bot.text("APPEAL 670000055"), "appeal.choose_kind")


def test_foreign_sender_cannot_appeal(bot, reported):
    from tchekam.appeals import flow
    from tchekam.conversations.models import Conversation
    from tchekam.conversations.router import Context
    from tchekam.messaging.channel import InboundMessage

    foreign = BotUser.objects.create(wa_phone="+33612345678", language="en")
    conv = Conversation.objects.create(user=foreign)
    msg = InboundMessage(
        "m", "33612345678", None, "private", None, "text", "APPEAL", None, None, ""
    )
    replies = flow.start(Context(user=foreign, conversation=conv, msg=msg))
    assert replies[0].text == t("appeal.cm_only", EN)


def test_number_typed_in_the_flow_is_never_a_target(bot, make_report, reported):
    other = make_report(incident=months_ago(4), phone="+237699123456")
    start(bot)
    bot.text("1")
    bot.text("This is about 699123456 which is mine")
    assert says(bot.text("DONE"), "appeal.submitted")
    appeal = Appeal.objects.get()
    assert appeal.phone_number.e164 == OWN
    assert other.subjects.get().phone_number.e164 != appeal.phone_number.e164


def test_full_wrong_flow_creates_open_appeal_and_f1_shows_it(
    bot, reported, django_capture_on_commit_callbacks
):
    assert not band_for_phone(OWN).under_appeal  # warms the cache
    assert cache.get(cache_key(OWN)) is not None
    start(bot)
    assert says(bot.text("1"), "appeal.ask_statement", n=1000)
    assert says(bot.text("I never sold anything"), "appeal.ask_evidence")
    with django_capture_on_commit_callbacks(execute=True):
        texts = bot.text("DONE")
    assert says(texts, "appeal.submitted")
    assert not any(w in texts[0].lower() for w in BANNED)
    appeal = Appeal.objects.get()
    assert (appeal.status, appeal.kind, appeal.appellant) == ("open", "wrong", bot.user)
    assert appeal.statement == "I never sold anything"
    assert appeal.submitted_at is not None
    assert bot.conversation.flow == "idle"
    assert AuditLog.objects.filter(action="appeal.submit").exists()
    # The warm cache was dropped, so the band changed at once.
    assert band_for_phone(OWN).under_appeal
    assert t("check.number.under_appeal", EN) in bot.text("670000055")[0]


def test_new_to_me_flow_stores_month(bot, reported):
    start(bot)
    assert says(bot.text("2"), "appeal.ask_month")
    assert says(bot.text("not a date"), "appeal.month_invalid")
    assert says(bot.text("12/2999"), "appeal.month_invalid")
    assert says(bot.text("juin 2026"), "appeal.ask_statement", n=1000)
    bot.text("I got this SIM recently")
    bot.text("DONE")
    appeal = Appeal.objects.get()
    assert appeal.kind == "new_to_me"
    assert str(appeal.number_acquired_at) == "2026-06-01"
    # Not approved yet: the band still counts every report.
    assert band_for_phone(OWN).band == Band.RED


def test_kind_and_statement_validation(bot, reported):
    start(bot)
    assert says(bot.text("what"), "appeal.choose_kind")
    bot.text("1")
    assert says(bot.text("x" * 1001), "appeal.statement_too_long", n=1000)
    assert says(bot.image(), "appeal.ask_statement", n=1000)
    assert bot.text("a" * 1000)


def test_evidence_is_stored_and_done_submits(bot, reported, object_store):
    start(bot)
    bot.text("1")
    bot.text("Not mine")
    data = png("green")
    assert says(bot.image(data), "appeal.file_noted")
    assert says(bot.audio(b"voice"), "appeal.file_noted")
    assert says(bot.text("blah"), "appeal.ask_evidence")
    bot.text("DONE")
    items = list(AppealEvidence.objects.order_by("pk"))
    assert [i.mimetype for i in items] == ["image/png", "audio/ogg"]
    assert object_store.get(items[0].object_key) == data
    assert items[0].appeal == Appeal.objects.get()


def test_failed_download_tells_the_user_and_keeps_going(bot, reported):
    start(bot)
    bot.text("1")
    bot.text("Not mine")
    bot.image(seed=False)
    assert not AppealEvidence.objects.exists()
    assert says(bot.text("DONE"), "appeal.submitted")


def test_item_limit(bot, reported):
    start(bot)
    bot.text("1")
    bot.text("Not mine")
    for i in range(5):
        bot.image(png(f"#0{i}0000"))
    assert says(bot.image(png("#ffffff")), "appeal.limit_items")
    assert AppealEvidence.objects.count() == 5


def test_cancel_discards_the_draft_and_files(bot, reported, object_store):
    start(bot)
    bot.text("1")
    bot.text("Not mine")
    bot.image()
    key = AppealEvidence.objects.get().object_key
    assert says(bot.text("cancel"), "appeal.cancelled")
    assert not Appeal.objects.exists()
    assert not object_store.exists(key)
    assert bot.conversation.flow == "idle"


def test_restarting_replaces_the_old_draft(bot, reported):
    start(bot)
    bot.text("1")
    first = Appeal.objects.get().pk
    start(bot)
    assert not Appeal.objects.filter(pk=first).exists()


def test_one_open_appeal_per_user(bot, reported):
    start(bot)
    bot.text("1")
    bot.text("Not mine")
    bot.text("DONE")
    assert says(bot.text("APPEAL"), "appeal.already_open")


def test_open_appeal_by_someone_else_is_not_duplicated(bot, reported):
    other = BotUser.objects.create(wa_phone="+237699000999", language="en")
    Appeal.objects.create(
        phone_number=reported.subjects.get().phone_number,
        appellant=other,
        kind="wrong",
        status="open",
        submitted_at=timezone.now(),
    )
    assert says(bot.text("APPEAL"), "appeal.number_busy")


def test_daily_limit(bot, reported, settings):
    settings.APPEALS_PER_DAY = 1
    phone = reported.subjects.get().phone_number
    Appeal.objects.create(
        phone_number=phone,
        appellant=bot.user,
        kind="wrong",
        status="rejected",
        submitted_at=timezone.now() - timedelta(minutes=5),
    )
    assert says(bot.text("APPEAL"), "appeal.limit_reached")


def test_expired_flow_is_dropped_by_router(bot, reported):
    start(bot)
    conv = bot.conversation
    conv.expires_at = timezone.now() - timedelta(minutes=1)
    conv.save()
    assert not says(bot.text("1"), "appeal.ask_statement", n=1000)
