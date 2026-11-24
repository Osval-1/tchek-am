"""The web reverse-image-search boundary: everything outside imaging searches through here.

Providers return `WebMatch`es whose `kind` is decided by `classify`, so swapping provider
(SerpAPI today, Google Vision Web Detection later) never changes what "catalogue" means.
"""

from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from django.conf import settings

Kind = Literal["catalogue", "marketplace", "social", "other"]

# Brand label -> kind. Brands are matched as a whole DNS label next to a registrable suffix
# (see `classify`), so jumia.cm, jumia.com.ng and fr.aliexpress.com match but notaliexpress.com
# does not. The marketplace list is deliberately small: add local classifieds as they show up.
_BRANDS: dict[str, Kind] = {
    **dict.fromkeys(
        ("aliexpress", "alibaba", "jumia", "temu", "shein", "amazon", "ebay"), "catalogue"
    ),
    **dict.fromkeys(("facebook", "instagram", "tiktok"), "social"),
    **dict.fromkeys(("jiji", "olx", "kupatana"), "marketplace"),
}
_GENERIC_TLDS = frozenset({"com", "net", "org"})
_SECOND_LEVELS = frozenset({"com", "co", "net", "org", "gov", "edu", "ac"})


@dataclass(frozen=True)
class WebMatch:
    url: str
    title: str
    source_domain: str
    kind: Kind

    def to_json(self) -> dict[str, str]:
        return {
            "url": self.url,
            "title": self.title,
            "source_domain": self.source_domain,
            "kind": self.kind,
        }

    @classmethod
    def from_json(cls, data: dict) -> "WebMatch":
        return cls(data["url"], data["title"], data["source_domain"], data["kind"])


class WebSearchError(Exception):
    """A search that did not complete. Messages carry class names and status codes only."""


class WebImageSearch(Protocol):
    def search(self, image_url: str) -> list[WebMatch]:
        """Pages where the image at `image_url` appears.

        Raises WebSearchError when the search did not complete, so a failure is never mistaken
        for "no matches" and cached as such.
        """
        ...


def _is_suffix(tail: list[str]) -> bool:
    """A registrable tail: tld (com/net/org or a 2-letter ccTLD) or co.xx style."""
    if len(tail) == 1:
        return tail[0] in _GENERIC_TLDS or (len(tail[0]) == 2 and tail[0].isalpha())
    return len(tail) == 2 and tail[0] in _SECOND_LEVELS and len(tail[1]) == 2 and tail[1].isalpha()


def classify(url: str) -> tuple[str, Kind] | None:
    """(source_domain, kind) for an http(s) URL, or None when it is not a usable web URL.

    The brand must be a whole label directly followed by a registrable suffix, taking the
    rightmost such label: `aliexpress.com.evil.com` and `aliexpress.evil.com` fail because
    what follows the brand is not a suffix, and `notaliexpress.com` is a different label.
    """
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except (ValueError, AttributeError):
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    labels = host.split(".")
    for i in range(len(labels) - 2, -1, -1):
        if labels[i] in _BRANDS and _is_suffix(labels[i + 1 :]):
            return ".".join(labels[i:]), _BRANDS[labels[i]]
    return host.removeprefix("www."), "other"


class FakeWebImageSearch:
    """Canned results for tests and offline runs, consumed in order; empty once exhausted."""

    _instance: "FakeWebImageSearch | None" = None

    def __init__(self) -> None:
        self.reset()

    @classmethod
    def instance(cls) -> "FakeWebImageSearch":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reset(self) -> None:
        self.results: list[list[WebMatch]] = []
        self.calls: list[str] = []
        self.fail = False

    def search(self, image_url: str) -> list[WebMatch]:
        self.calls.append(image_url)
        if self.fail:
            raise WebSearchError("fake failure")
        return self.results.pop(0) if self.results else []


class GoogleVisionWebDetectionProvider:
    """Swap-in for SerpAPI: Google Cloud Vision `WEB_DETECTION` (not implemented).

    To switch: call `images:annotate` with `{"image": {"source": {"imageUri": image_url}},
    "features": [{"type": "WEB_DETECTION"}]}`, map `webDetection.pagesWithMatchingImages[]`
    (`url`, `pageTitle`) through `classify` into `WebMatch`es, raise `WebSearchError` on failure
    (class name and status only, never the URL or key), then register it in `get_web_search`
    under a new `WEB_SEARCH_BACKEND` value. Nothing else in the app needs to change.
    """

    def search(self, image_url: str) -> list[WebMatch]:
        raise NotImplementedError("Google Vision web detection is not wired up yet")


def get_web_search() -> WebImageSearch:
    backend = settings.WEB_SEARCH_BACKEND
    if backend == "fake":
        return FakeWebImageSearch.instance()
    if backend == "serpapi":
        # Lazy so this factory stays the only place that names the provider adapter.
        from .serpapi import SerpApiLensProvider

        return SerpApiLensProvider()
    raise ValueError(f"Unknown WEB_SEARCH_BACKEND: {backend!r}")
