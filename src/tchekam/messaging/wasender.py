"""WaSender HTTP adapter. Only tchekam.messaging may import this module (see the boundary test)."""

from typing import Any
from urllib.parse import quote

import httpx

from .channel import MAX_MEDIA_BYTES, ChannelError, InboundMessage, MediaTooLarge, RateLimited

TIMEOUT_SECONDS = 10.0
DEFAULT_RETRY_AFTER = 60
MAX_RETRY_AFTER = 3600


def _retry_after(value: Any) -> int:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError, OverflowError):  # missing, garbage, nan, inf
        return DEFAULT_RETRY_AFTER
    return min(max(seconds, 1), MAX_RETRY_AFTER)


class WaSenderChannel:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://www.wasenderapi.com/api",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT_SECONDS,
            transport=transport,
        )
        # Separate client for the one-hour public media URL: it must never see our API key.
        self._media = httpx.Client(
            timeout=TIMEOUT_SECONDS, transport=transport, follow_redirects=True
        )

    def send_text(self, to: str, text: str) -> None:
        self._call("POST", "send-message", {"to": to, "text": text})

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> None:
        body = {"to": to, "imageUrl": image_url}
        if caption:
            body["text"] = caption
        self._call("POST", "send-message", body)

    def send_typing(self, jid: str, ms: int) -> None:
        self._call("POST", "send-presence-update", {"jid": jid, "type": "composing", "delayMs": ms})

    def leave_group(self, group_jid: str) -> None:
        self._call("POST", f"groups/{quote(group_jid, safe='@.')}/leave")

    def group_metadata(self, group_jid: str) -> dict[str, Any]:
        body = self._call("GET", f"groups/{quote(group_jid, safe='@.')}/metadata")
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    def download_media(self, msg: InboundMessage) -> tuple[bytes, str]:
        if not msg.media or not isinstance(msg.media.get("type"), str):
            raise ChannelError("message has no media")
        media_type = msg.media["type"]
        descriptor = {k: v for k, v in msg.media.items() if k != "type"}
        body = self._call(
            "POST",
            "decrypt-media",
            {
                "data": {
                    "messages": {"key": {"id": msg.message_id}, "message": {media_type: descriptor}}
                }
            },
        )
        url = body.get("publicUrl")
        if not isinstance(url, str) and isinstance(body.get("data"), dict):
            url = body["data"].get("publicUrl")
        if not isinstance(url, str) or not url:
            raise ChannelError("decrypt-media returned no publicUrl")
        data, mimetype = self._fetch(url)
        fallback = descriptor.get("mimetype")
        return data, mimetype or (
            fallback if isinstance(fallback, str) else "application/octet-stream"
        )

    def _fetch(self, url: str) -> tuple[bytes, str]:
        try:
            with self._media.stream("GET", url) as resp:
                if not resp.is_success:
                    raise ChannelError(f"media fetch failed: HTTP {resp.status_code}")
                declared = resp.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > MAX_MEDIA_BYTES:
                    raise MediaTooLarge("media exceeds size limit")
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_MEDIA_BYTES:
                        raise MediaTooLarge("media exceeds size limit")
                    chunks.append(chunk)
                mimetype = resp.headers.get("Content-Type", "").strip()
        except httpx.HTTPError as exc:
            raise ChannelError(f"media fetch failed: {type(exc).__name__}") from exc
        return b"".join(chunks), mimetype

    def _call(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        # Error text names the endpoint and status only: never bodies or recipients.
        endpoint = path.split("/")[0]
        try:
            resp = self._api.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise ChannelError(f"WaSender {endpoint}: {type(exc).__name__}") from exc
        try:
            body = resp.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and "retry_after" in body:
            raise RateLimited(_retry_after(body["retry_after"]))
        if resp.status_code == 429:
            raise RateLimited(_retry_after(resp.headers.get("Retry-After")))
        if not resp.is_success or not isinstance(body, dict) or body.get("success") is False:
            raise ChannelError(f"WaSender {endpoint}: HTTP {resp.status_code}")
        return body
