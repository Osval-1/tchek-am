import json
import logging
from pathlib import Path

import httpx
import pytest

from tchekam.imaging.serpapi import SerpApiLensProvider, parse_visual_matches
from tchekam.imaging.web import (
    FakeWebImageSearch,
    GoogleVisionWebDetectionProvider,
    WebMatch,
    WebSearchError,
    classify,
    get_web_search,
)

FIXTURE = Path(__file__).parent / "fixtures" / "serpapi_google_lens.json"
SIGNED = "https://s3.example.com/bucket/thumbnails/abc?X-Amz-Signature=SIGSECRET"


def recorded() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# Classification ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "domain", "kind"),
    [
        ("https://fr.aliexpress.com/item/1.html", "aliexpress.com", "catalogue"),
        ("https://www.alibaba.com/product/1", "alibaba.com", "catalogue"),
        ("https://www.jumia.cm/x", "jumia.cm", "catalogue"),
        ("https://www.jumia.com.ng/x", "jumia.com.ng", "catalogue"),
        ("https://temu.com/x", "temu.com", "catalogue"),
        ("https://shein.com/x", "shein.com", "catalogue"),
        ("https://www.amazon.co.uk/dp/1", "amazon.co.uk", "catalogue"),
        ("https://www.ebay.com/itm/1", "ebay.com", "catalogue"),
        ("https://m.facebook.com/x", "facebook.com", "social"),
        ("https://www.instagram.com/p/1", "instagram.com", "social"),
        ("https://vm.tiktok.com/1", "tiktok.com", "social"),
        ("https://jiji.cm/douala/x.html", "jiji.cm", "marketplace"),
        ("https://olx.com.ng/x", "olx.com.ng", "marketplace"),
        ("https://blog.example.org/a", "blog.example.org", "other"),
        ("HTTPS://WWW.ALIEXPRESS.COM/x", "aliexpress.com", "catalogue"),
    ],
)
def test_classify_known_domains(url, domain, kind):
    assert classify(url) == (domain, kind)


@pytest.mark.parametrize(
    "url",
    [
        "https://notaliexpress.com/x",
        "https://aliexpress.com.evil.com/x",
        "https://aliexpress.evil.com/x",
        "https://evil.com/aliexpress.com",
        "https://evil.com/?u=jumia.cm",
        "https://aliexpress.com@evil.com/x",
        "https://jumia-cm.shop/x",
        "https://facebook.com.phish.net/x",
    ],
)
def test_classify_rejects_lookalikes(url):
    assert classify(url)[1] == "other"


@pytest.mark.parametrize("url", ["", "not a url", "javascript:alert(1)", "ftp://aliexpress.com/x"])
def test_classify_unusable_urls(url):
    assert classify(url) is None


# Parsing the recorded fixture ----------------------------------------------------------------


def test_parse_recorded_fixture_gives_classified_matches():
    matches = parse_visual_matches(recorded())

    assert [(m.source_domain, m.kind) for m in matches] == [
        ("aliexpress.com", "catalogue"),
        ("jumia.cm", "catalogue"),
        ("jiji.cm", "marketplace"),
        ("facebook.com", "social"),
        ("aliexpress.com", "catalogue"),
        ("techblog.example.org", "other"),
        ("notaliexpress.com", "other"),
    ]
    first = matches[0]
    assert first.url == "https://fr.aliexpress.com/item/1005006123456789.html"
    assert first.title.startswith("Smartphone 6.7 inch")
    assert matches[-1].title == ""  # null title tolerated


@pytest.mark.parametrize(
    "payload",
    [{}, {"visual_matches": None}, {"visual_matches": "x"}, [], "nope", None],
)
def test_parse_defensive_against_odd_shapes(payload):
    assert parse_visual_matches(payload) == []


def test_parse_caps_title_and_drops_absurdly_long_urls():
    payload = {
        "visual_matches": [
            {"title": "t" * 1000, "link": "https://a.com/ok"},
            {"title": "x", "link": "https://a.com/" + "p" * 3000},  # truncating would break it
        ]
    }

    (match,) = parse_visual_matches(payload)

    assert len(match.title) == 200


def test_parse_no_results_error_is_empty_other_errors_raise():
    no_results = {"error": "Google Lens hasn't returned any results for this query."}
    assert parse_visual_matches(no_results) == []
    with pytest.raises(WebSearchError):
        parse_visual_matches({"error": "Invalid API key. Your API key should be here: SECRET"})


# The HTTP adapter ----------------------------------------------------------------------------


def adapter(handler) -> SerpApiLensProvider:
    return SerpApiLensProvider(api_key="KEY123", transport=httpx.MockTransport(handler))


def test_adapter_sends_expected_request_and_parses():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=recorded())

    matches = adapter(handler).search(SIGNED)

    (request,) = seen
    assert request.method == "GET"
    assert request.url.host == "serpapi.com" and request.url.path == "/search.json"
    assert request.url.params["engine"] == "google_lens"
    assert request.url.params["url"] == SIGNED
    assert request.url.params["api_key"] == "KEY123"
    assert request.extensions["timeout"]["read"] == 20.0
    assert len(matches) == 7


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom KEY123"),
        httpx.Response(401, json={"error": "Invalid API key KEY123"}),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"error": "Your account has run out of searches."}),
    ],
)
def test_adapter_failures_raise_without_leaking_secrets(response, caplog):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(WebSearchError) as info:
        adapter(lambda request: response).search(SIGNED)

    text = f"{info.value!s} {info.value!r} {info.value.__cause__!r} {info.value.__context__!r}"
    assert "KEY123" not in text and "SIGSECRET" not in text
    assert "KEY123" not in caplog.text and "SIGSECRET" not in caplog.text


def test_adapter_transport_error_does_not_leak_url():
    def handler(request):
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    with pytest.raises(WebSearchError) as info:
        adapter(handler).search(SIGNED)

    assert "KEY123" not in str(info.value) and "SIGSECRET" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


# Fake, stub, factory -------------------------------------------------------------------------


def test_fake_returns_queued_results_and_records_calls():
    fake = FakeWebImageSearch()
    match = WebMatch("https://a.com/x", "t", "a.com", "other")
    fake.results.append([match])

    assert fake.search("u1") == [match]
    assert fake.search("u2") == []
    assert fake.calls == ["u1", "u2"]


def test_fake_can_fail():
    fake = FakeWebImageSearch()
    fake.fail = True
    with pytest.raises(WebSearchError):
        fake.search("u")


def test_google_vision_stub_is_a_documented_swap_point():
    assert "WEB_DETECTION" in GoogleVisionWebDetectionProvider.__doc__
    with pytest.raises(NotImplementedError):
        GoogleVisionWebDetectionProvider().search("u")


def test_factory_follows_the_backend_setting(settings):
    settings.WEB_SEARCH_BACKEND = "fake"
    assert isinstance(get_web_search(), FakeWebImageSearch)
    settings.WEB_SEARCH_BACKEND = "serpapi"
    settings.SERPAPI_API_KEY = "k"
    assert isinstance(get_web_search(), SerpApiLensProvider)
    settings.WEB_SEARCH_BACKEND = "nope"
    with pytest.raises(ValueError):
        get_web_search()
