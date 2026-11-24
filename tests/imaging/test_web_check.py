from datetime import timedelta

import pytest
from django.utils import timezone

from tchekam.conversations.models import BotUser
from tchekam.i18n import t
from tchekam.imaging import webcheck
from tchekam.imaging.ingest import SightingContext, ingest
from tchekam.imaging.models import WebSearchResult, WebSearchUsage
from tchekam.imaging.tasks import web_check
from tchekam.imaging.web import WebMatch
from tests.imaging.helpers import encode, structured_image

pytestmark = pytest.mark.django_db

SUBMISSION, REPORT = "submission", "report"
FORBIDDEN = ("scammer", "fraud", "arnaqueur", "fraude")


def sha(n: int) -> str:
    return f"{n:064x}"


def match(domain: str, kind: str) -> WebMatch:
    return WebMatch(f"https://{domain}/item/1", f"Item on {domain}", domain, kind)


@pytest.fixture(autouse=True)
def _fake_web(fake_web):
    return fake_web


@pytest.fixture
def user():
    return BotUser.objects.create(wa_phone="+237670000099", language="en")


@pytest.fixture
def image(user):
    data = encode(structured_image(4))
    return ingest(data, "submission", SightingContext(context="submission", bot_user=user))


# lookup: cache, caps ------------------------------------------------------------------------


def test_lookup_calls_provider_with_a_signed_url_and_caches(fake_web, user):
    fake_web.results.append([match("jumia.cm", "catalogue")])

    first = webcheck.lookup(sha(1), "thumbnails/k1", user=user, purpose=SUBMISSION)
    second = webcheck.lookup(sha(1), "thumbnails/k1", user=user, purpose=SUBMISSION)

    assert first == second == [match("jumia.cm", "catalogue")]
    assert fake_web.calls == ["memory://thumbnails/k1?ttl=600"]  # short-lived signed URL
    assert WebSearchUsage.objects.count() == 1  # the cache hit is free
    assert WebSearchResult.objects.get(sha256=sha(1)).matches[0]["source_domain"] == "jumia.cm"


def test_cache_hit_is_served_even_when_every_cap_is_exhausted(settings, fake_web, user):
    settings.WEB_SEARCH_MONTHLY_BUDGET = 1
    settings.WEB_SEARCH_PER_USER_DAY = 1
    fake_web.results.append([match("jumia.cm", "catalogue")])
    webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION)

    again = webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION)

    assert again == [match("jumia.cm", "catalogue")]
    assert len(fake_web.calls) == 1


def test_cache_expires_after_30_days(fake_web, user):
    webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION)
    WebSearchResult.objects.update(checked_at=timezone.now() - timedelta(days=31))

    webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION)

    assert len(fake_web.calls) == 2
    assert WebSearchResult.objects.count() == 1  # refreshed in place


def test_an_empty_result_is_cached_too(fake_web, user):
    assert webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION) == []
    assert webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION) == []
    assert len(fake_web.calls) == 1


def test_per_user_daily_cap(settings, fake_web, user):
    settings.WEB_SEARCH_PER_USER_DAY = 2
    other = BotUser.objects.create(wa_phone="+237670000098")

    assert webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION) is not None
    assert webcheck.lookup(sha(2), "k", user=user, purpose=SUBMISSION) is not None
    assert webcheck.lookup(sha(3), "k", user=user, purpose=SUBMISSION) is None
    assert len(fake_web.calls) == 2
    # Another user is unaffected, and the refused one left no usage row behind.
    assert webcheck.lookup(sha(3), "k", user=other, purpose=SUBMISSION) is not None
    assert WebSearchUsage.objects.filter(user=user).count() == 2


def test_per_user_cap_resets_the_next_local_day(settings, fake_web, user):
    settings.WEB_SEARCH_PER_USER_DAY = 1
    webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION)
    WebSearchUsage.objects.update(created_at=timezone.now() - timedelta(days=1, hours=1))

    assert webcheck.lookup(sha(2), "k", user=user, purpose=SUBMISSION) is not None


def test_monthly_budget_is_global_and_blocks_everyone(settings, fake_web, user):
    settings.WEB_SEARCH_MONTHLY_BUDGET = 2
    other = BotUser.objects.create(wa_phone="+237670000098")

    assert webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION) is not None
    assert webcheck.lookup(sha(2), "k", user=other, purpose=SUBMISSION) is not None
    assert webcheck.lookup(sha(3), "k", user=user, purpose=SUBMISSION) is None
    assert webcheck.lookup(sha(3), "k", user=None, purpose=REPORT) is None  # not bypassed
    assert len(fake_web.calls) == 2


def test_budget_starts_over_in_a_new_local_month(settings, fake_web, user):
    settings.WEB_SEARCH_MONTHLY_BUDGET = 1
    webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION)
    start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    WebSearchUsage.objects.update(created_at=start - timedelta(minutes=1))

    assert webcheck.lookup(sha(2), "k", user=user, purpose=SUBMISSION) is not None


def test_report_images_bypass_the_per_user_cap_but_still_count(settings, fake_web, user):
    settings.WEB_SEARCH_PER_USER_DAY = 1
    for n in range(1, 4):
        assert webcheck.lookup(sha(n), "k", user=user, purpose=REPORT) is not None

    # Report calls neither hit the user cap nor use up the user's photo-check allowance.
    assert webcheck.lookup(sha(10), "k", user=user, purpose=SUBMISSION) is not None
    assert webcheck.lookup(sha(11), "k", user=user, purpose=SUBMISSION) is None
    assert WebSearchUsage.objects.filter(purpose=REPORT).count() == 3


def test_failure_is_not_cached_and_does_not_use_budget(settings, fake_web, user):
    settings.WEB_SEARCH_MONTHLY_BUDGET = 1
    fake_web.fail = True

    assert webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION) is None
    assert not WebSearchResult.objects.exists()
    assert not WebSearchUsage.objects.exists()

    fake_web.fail = False
    assert webcheck.lookup(sha(1), "k", user=user, purpose=SUBMISSION) == []


def test_cached_matches_for_the_review_page_ignores_age(fake_web, user):
    assert webcheck.cached_matches(sha(1)) is None
    fake_web.results.append([match("jiji.cm", "marketplace")])
    webcheck.lookup(sha(1), "k", user=user, purpose=REPORT)
    WebSearchResult.objects.update(checked_at=timezone.now() - timedelta(days=90))

    found = webcheck.cached_matches(sha(1))

    assert found == [match("jiji.cm", "marketplace")]


# imaging.web_check: the follow-up ------------------------------------------------------------


def run(image, user):
    web_check(image_id=image.pk, user_id=user.pk)


def test_catalogue_match_sends_one_followup_with_domains_only(fake_web, fake_channel, image, user):
    fake_web.results.append(
        [
            match("aliexpress.com", "catalogue"),
            match("jumia.cm", "catalogue"),
            match("jiji.cm", "marketplace"),
            match("aliexpress.com", "catalogue"),  # duplicate domain
            match("shein.com", "catalogue"),  # fourth distinct: cut
            match("facebook.com", "social"),
        ]
    )

    run(image, user)

    (sent,) = fake_channel.sent
    assert sent["text"] == t(
        "check.photo.online", "en", domains="aliexpress.com, jumia.cm, jiji.cm"
    )
    assert sent["text"].startswith("🔎 This photo also appears online: ")
    assert "http" not in sent["text"] and "facebook" not in sent["text"]
    assert "shein" not in sent["text"]
    assert not any(word in sent["text"].lower() for word in FORBIDDEN)


def test_uses_the_stored_thumbnail_signed_url(fake_web, fake_channel, image, user):
    run(image, user)

    assert fake_web.calls == [f"memory://{image.thumbnail_key}?ttl=600"]


@pytest.mark.parametrize("lang", ["fr", "pcm"])
def test_followup_is_localised(fake_web, fake_channel, image, user, lang):
    user.language = lang
    user.save()
    fake_web.results.append([match("jumia.cm", "catalogue")])

    run(image, user)

    assert fake_channel.sent[0]["text"] == t("check.photo.online", lang, domains="jumia.cm")


@pytest.mark.parametrize(
    "matches",
    [[], [match("facebook.com", "social"), match("blog.example.org", "other")]],
)
def test_no_catalogue_or_marketplace_match_means_no_message(
    fake_web, fake_channel, image, user, matches
):
    fake_web.results.append(matches)

    run(image, user)

    assert fake_channel.sent == []


def test_provider_failure_and_caps_send_nothing_and_never_raise(
    settings, fake_web, fake_channel, image, user
):
    fake_web.fail = True
    run(image, user)
    fake_web.fail = False
    settings.WEB_SEARCH_PER_USER_DAY = 0
    run(image, user)

    assert fake_channel.sent == []
    assert fake_web.calls == [f"memory://{image.thumbnail_key}?ttl=600"]  # only the failed one


def test_cached_result_is_followed_up_without_a_provider_call(fake_web, fake_channel, image, user):
    fake_web.results.append([match("jumia.cm", "catalogue")])
    run(image, user)
    run(image, user)

    assert len(fake_web.calls) == 1
    assert len(fake_channel.sent) == 2


def test_missing_rows_and_blocked_users_are_ignored(fake_web, fake_channel, image, user):
    web_check(image_id=0, user_id=user.pk)
    web_check(image_id=image.pk, user_id=0)
    user.blocked = True
    user.save()
    fake_web.results.append([match("jumia.cm", "catalogue")])
    run(image, user)

    assert fake_channel.sent == []


def test_image_without_a_stored_thumbnail_is_skipped(fake_web, fake_channel, image, user):
    image.thumbnail_key = ""
    image.save()

    run(image, user)

    assert fake_web.calls == []


def test_unexpected_errors_are_swallowed(monkeypatch, fake_channel, image, user):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(webcheck, "lookup", boom)

    run(image, user)

    assert fake_channel.sent == []
