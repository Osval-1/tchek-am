import logging

import pytest
from django.core.cache import cache
from django.utils import timezone

from tchekam.checks import photo
from tchekam.checks.models import CheckLog
from tchekam.conversations.models import BotUser, Conversation
from tchekam.conversations.router import Context
from tchekam.i18n import t
from tchekam.identifiers.models import get_or_create_phone
from tchekam.imaging.ingest import SightingContext, ingest
from tchekam.imaging.models import Image, ImageSighting
from tchekam.messaging.channel import InboundMessage
from tchekam.reports.models import Report
from tests.imaging.helpers import VARIANTS, encode, structured_image
from tests.reports.conftest import SENDER, Bot, png

from .test_number import seed

pytestmark = pytest.mark.django_db

NUMBER_A, NUMBER_B = "+237677123456", "+237699111222"
GROUP_NAME = "Marché Mokolo Deals"
FORBIDDEN = ("scammer", "fraud", "arnaqueur", "677", "699", GROUP_NAME)


@pytest.fixture(autouse=True)
def _env(object_store):
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def bot(fake_channel):
    user = BotUser.objects.create(wa_phone=f"+{SENDER}", language="en")
    Conversation.objects.create(user=user)
    return Bot(fake_channel, user)


def seen_by(img, number, **kw):
    """A sighting of `img` tied to a seller number (and a group id, which must never surface)."""
    ctx = SightingContext(context="group", phone_number=get_or_create_phone(number), **kw)
    return ingest(encode(img), "group", ctx)


def send_photo(bot, img, choice="1"):
    bot.image(encode(img))
    return bot.text(choice)


def assert_clean(texts):
    for text in texts:
        for word in FORBIDDEN:
            assert word.lower() not in text.lower()


def test_no_match_reply_and_log(bot):
    texts = send_photo(bot, structured_image(4))

    assert texts[0] == t("check.photo.checking", "en")
    assert "No matches in our database yet" in texts[1]
    assert "Tips:" in texts[1]
    assert_clean(texts)
    log = CheckLog.objects.get()
    assert (log.kind, log.result_band, log.user) == ("image", "none", bot.user)
    assert log.subject_ref == Image.objects.get().sha256
    sighting = ImageSighting.objects.get()
    assert (sighting.context, sighting.bot_user) == ("submission", bot.user)
    assert sighting.phone_number is None
    assert bot.conversation.flow == "idle"


def test_two_numbers_match_reply(bot):
    img = structured_image(4)
    seen_by(img, NUMBER_A, group_id=7)
    seen_by(VARIANTS["resized"](img), NUMBER_B, group_id=8)  # near-duplicate, another seller
    first_seen = timezone.now()

    texts = send_photo(bot, img)

    expected = f"This photo was posted by 2 different numbers, first seen {first_seen:%B %Y}."
    assert expected in texts[1]
    assert "reviewed reports" not in texts[1]
    assert_clean(texts)
    assert CheckLog.objects.get().result_band == "none"


def test_match_reply_in_french_and_singular(bot):
    bot.user.language = "fr"
    bot.user.save()
    img = structured_image(4)
    seen_by(img, NUMBER_A)

    texts = send_photo(bot, img)

    assert "publiée par 1 numéro" in texts[1]
    assert_clean(texts)


def test_flagged_number_adds_warning(bot):
    img = structured_image(4)
    seen_by(img, NUMBER_A)
    seen_by(img, NUMBER_B)
    seed("approved", e164=NUMBER_A)

    texts = send_photo(bot, img)

    assert "⚠ One of these numbers has reviewed reports." in texts[1]
    assert "different numbers" in texts[1]
    assert_clean(texts)
    assert CheckLog.objects.get().result_band == "orange"


def test_match_without_known_numbers_is_still_sensible(bot):
    img = structured_image(4)
    other = BotUser.objects.create(wa_phone="+237670000001")
    near = VARIANTS["resized"](img)  # a different file, so a different Image row
    ingest(encode(near), "submission", SightingContext(context="submission", bot_user=other))

    texts = send_photo(bot, img)

    assert "already in our database" in texts[1]
    assert "no number linked" in texts[1]
    assert "0 different" not in texts[1]


def test_own_repeat_submission_is_not_a_match(bot):
    img = structured_image(4)
    send_photo(bot, img)
    texts = send_photo(bot, img)

    assert "No matches in our database yet" in texts[1]
    assert CheckLog.objects.count() == 2


def test_menu_2_then_image_runs_the_check(bot):
    assert bot.text("2") == [t("prompt.send_photo", "en")]
    texts = bot.image(encode(structured_image(4)))

    assert "No matches in our database yet" in texts[1]


def test_choice_2_starts_report_with_the_image(bot):
    bot.image(png("green"))
    texts = bot.text("2")

    assert texts[0] == t("report.instructions", "en")
    report = Report.objects.get(reporter=bot.user)
    assert report.evidence.count() == 1
    assert not CheckLog.objects.exists()
    assert not ImageSighting.objects.exists()


def test_over_limit_gets_limit_copy_and_no_work(bot, settings):
    settings.CHECKS_PER_DAY = 1
    send_photo(bot, structured_image(4))

    texts = send_photo(bot, structured_image(2))

    assert texts == [t("check.limit_reached", "en")]
    assert CheckLog.objects.count() == 1
    assert Image.objects.count() == 1


def test_limit_is_rechecked_when_the_job_runs(bot, settings):
    settings.CHECKS_PER_DAY = 1
    bot.image(encode(structured_image(4)))
    CheckLog.objects.create(user=bot.user, kind="number", subject_ref="x", result_band="green")
    bot.channel.sent.clear()

    # Skips the handler's early check, as a parallel photo would.
    photo.check_photo(user_id=bot.user.pk, message_id=bot.last_id)

    assert [m["text"] for m in bot.channel.sent] == [t("check.limit_reached", "en")]
    assert CheckLog.objects.count() == 1


def test_rejected_image_gets_friendly_error_and_no_log(bot):
    bot.image(b"not an image at all")
    texts = bot.text("1")

    assert texts[-1] == t("check.photo.rejected", "en")
    assert not CheckLog.objects.exists()


def test_failed_download_gets_friendly_error(bot):
    bot.image(seed=False)
    texts = bot.text("1")

    assert texts[-1] == t("check.photo.failed", "en")
    assert not CheckLog.objects.exists()


def test_unexpected_error_is_reported_and_never_raised(bot, monkeypatch, caplog):
    def boom(image):
        raise RuntimeError("db down")

    monkeypatch.setattr(photo, "find_similar", boom)
    bot.image(encode(structured_image(4)))
    with caplog.at_level(logging.WARNING):
        texts = bot.text("1")

    assert texts[-1] == t("check.photo.failed", "en")
    assert "RuntimeError" in caplog.text


def test_task_ignores_unknown_user_and_foreign_message(bot):
    photo.check_photo(user_id=999999, message_id="x")
    bot.image(encode(structured_image(4)))
    other = BotUser.objects.create(wa_phone="+237670000002", language="en")
    bot.channel.sent.clear()

    photo.check_photo(user_id=other.pk, message_id=bot.last_id)  # not their message

    assert [m["text"] for m in bot.channel.sent] == [t("check.photo.failed", "en")]
    assert not ImageSighting.objects.exists()


def test_handler_without_image_id_asks_to_resend(bot):
    msg = InboundMessage("m", SENDER, None, "private", None, "text", "1", None, None, "x")
    ctx = Context(user=bot.user, conversation=bot.conversation, msg=msg)

    assert photo.handle_check_photo(ctx)[0].text == t("check.photo.failed", "en")
    assert ctx.jobs == []


def test_follow_up_seam_runs_after_the_reply(bot, monkeypatch):
    calls = []
    monkeypatch.setattr(photo, "after_first_reply", lambda user, image: calls.append(image.pk))

    send_photo(bot, structured_image(4))

    assert calls == [Image.objects.get().pk]


def test_follow_up_seam_default_is_a_no_op(bot):
    assert photo.after_first_reply(bot.user, Image(sha256="x")) is None
