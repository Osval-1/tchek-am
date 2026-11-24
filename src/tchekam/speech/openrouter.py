"""Fail-closed STT adapter: current routing cannot enforce approved endpoint lists.

OpenRouter STT docs checked 2026-11-24 explicitly exclude `only`, `order`, `ignore`
from transcription routing. No network is attempted, even with a configured key.
Reopen A0 before adding transport; chat privacy settings cannot be copied here.
"""

from .base import Transcript


class OpenRouterSTT:
    unavailable_reason = "endpoint_allowlist_unsupported"

    def transcribe(
        self, audio: bytes, mimetype: str, language_hint: str | None = None
    ) -> Transcript:
        return Transcript()
