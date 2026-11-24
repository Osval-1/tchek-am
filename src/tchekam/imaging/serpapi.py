"""SerpAPI Google Lens adapter. Only this module and web.py may name SerpAPI.

The request URL carries both the API key and the signed image URL, and httpx puts that URL in
its exception messages. So nothing from an httpx exception is ever logged or re-raised: errors
are reduced to a class name or status code and raised `from None`.
"""

import logging
from typing import Any

import httpx
from django.conf import settings

from .web import WebMatch, WebSearchError, classify

logger = logging.getLogger(__name__)

ENDPOINT = "https://serpapi.com/search.json"
TIMEOUT_SECONDS = 20.0
MAX_MATCHES = 30
MAX_TITLE = 200
MAX_URL = 500
# SerpAPI answers 200 with this error when Lens simply found nothing: not a failure.
_NO_RESULTS = "hasn't returned any results"


def parse_visual_matches(payload: Any) -> list[WebMatch]:
    """Classified matches from a SerpAPI response body. Tolerates odd shapes; skips bad rows."""
    if not isinstance(payload, dict):
        return []
    error = payload.get("error")
    if error:
        if isinstance(error, str) and _NO_RESULTS in error:
            return []
        # The error text can echo the key or URL: report only that there was one.
        raise WebSearchError("SerpAPI reported an error")
    rows = payload.get("visual_matches")
    if not isinstance(rows, list):
        return []
    matches: list[WebMatch] = []
    for row in rows:
        link = row.get("link") if isinstance(row, dict) else None
        classified = classify(link) if isinstance(link, str) and len(link) <= MAX_URL else None
        if classified is None:
            continue
        title = row.get("title")
        domain, kind = classified
        matches.append(
            WebMatch(
                url=link, title=title[:MAX_TITLE] if isinstance(title, str) else "",
                source_domain=domain, kind=kind,
            )
        )  # fmt: skip
        if len(matches) >= MAX_MATCHES:
            break
    return matches


class SerpApiLensProvider:
    def __init__(
        self, *, api_key: str | None = None, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._api_key = settings.SERPAPI_API_KEY if api_key is None else api_key
        self._transport = transport

    def search(self, image_url: str) -> list[WebMatch]:
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
                response = client.get(
                    ENDPOINT,
                    params={"engine": "google_lens", "url": image_url, "api_key": self._api_key},
                )
                response.raise_for_status()
                return parse_visual_matches(response.json())
        except WebSearchError:
            raise
        except httpx.HTTPStatusError as exc:
            reason = f"HTTPStatusError:{exc.response.status_code}"
        except Exception as exc:  # noqa: BLE001 - any failure must reach the caller as one type
            reason = type(exc).__name__
        logger.warning("web search failed: %s", reason)
        raise WebSearchError(reason) from None
