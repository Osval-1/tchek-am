import pytest

from tchekam.conversations.models import BotUser
from tchekam.imaging.models import WebSearchResult, WebSearchUsage
from tchekam.imaging.web import WebMatch
from tchekam.reports import hooks, tasks
from tchekam.reports.models import Evidence, Report
from tests.reports.conftest import extraction_json

pytestmark = pytest.mark.django_db

MATCH = WebMatch("https://www.aliexpress.com/item/1", "Phone", "aliexpress.com", "catalogue")


@pytest.fixture
def report(object_store):
    user = BotUser.objects.create(wa_phone="+237670000077", language="en")
    return Report.objects.create(reporter=user, status="draft")


def add(report, n, *, kind="other", mimetype="image/png"):
    key = f"evidence/k{n}"
    return Evidence.objects.create(
        report=report, kind=kind, object_key=key, mimetype=mimetype,
        sha256=f"{n:064x}", size_bytes=1,
    )  # fmt: skip


def test_images_are_searched_with_signed_urls_and_stored(report, fake_web):
    ev = add(report, 1, kind="post")
    fake_web.results.append([MATCH])

    tasks.web_check(report_id=report.pk)

    assert fake_web.calls == ["memory://evidence/k1?ttl=600"]
    assert WebSearchResult.objects.get(sha256=ev.sha256).matches[0]["kind"] == "catalogue"
    assert WebSearchUsage.objects.get().purpose == "report"


def test_chat_and_payment_screenshots_and_audio_are_never_sent_to_the_provider(report, fake_web):
    add(report, 1, kind="chat")
    add(report, 2, kind="momo_sms")
    add(report, 3, kind="voice", mimetype="audio/ogg")
    add(report, 4, kind="other", mimetype="application/pdf")

    tasks.web_check(report_id=report.pk)

    assert fake_web.calls == []


def test_report_images_bypass_the_per_user_cap_but_not_the_budget(report, fake_web, settings):
    settings.WEB_SEARCH_PER_USER_DAY = 1
    settings.WEB_SEARCH_MONTHLY_BUDGET = 3
    for n in range(1, 6):
        add(report, n)

    tasks.web_check(report_id=report.pk)

    assert len(fake_web.calls) == 3
    assert WebSearchResult.objects.count() == 3


def test_same_image_twice_is_one_call(report, fake_web):
    a, b = add(report, 1), add(report, 2)
    Evidence.objects.filter(pk=b.pk).update(sha256=a.sha256)

    tasks.web_check(report_id=report.pk)

    assert len(fake_web.calls) == 1


def test_a_failing_search_leaves_other_images_unharmed(report, fake_web):
    add(report, 1)
    fake_web.fail = True

    tasks.web_check(report_id=report.pk)  # does not raise

    assert not WebSearchResult.objects.exists()


def test_missing_report_is_ignored(fake_web):
    tasks.web_check(report_id=0)

    assert fake_web.calls == []


def test_after_extraction_enqueues_and_never_raises(report, fake_web, monkeypatch):
    add(report, 1)
    hooks.after_extraction(report)
    assert len(fake_web.calls) == 1

    def boom(*args, **kwargs):
        raise RuntimeError("queue down")

    monkeypatch.setattr(hooks, "enqueue", boom)
    hooks.after_extraction(report)  # extraction must not fail because the bonus check did


def test_end_to_end_report_image_gets_web_matches_after_extraction(bot, fake_llm, fake_web):
    fake_web.results.append([MATCH])
    fake_llm.responses["evidence_extraction"] = [extraction_json(evidence_kinds=["post"])]
    bot.text("4")
    bot.image()
    bot.text("DONE")

    ev = Evidence.objects.get()
    assert ev.kind == "post"
    row = WebSearchResult.objects.get(sha256=ev.sha256)
    assert row.matches[0]["source_domain"] == "aliexpress.com"
    assert ev.tamper_flags == []  # web matches never count as tampering
