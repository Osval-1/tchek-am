import logging
import math
import time
from typing import Any

import httpx
from django.conf import settings

from tchekam.ai.client import record_call

from .base import Transcript

logger = logging.getLogger(__name__)

PURPOSE = "stt"
TIMEOUT_SECONDS = 30.0
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Groq's upload limit
DEFAULT_TYPE = "audio/ogg"
# base mimetype -> (canonical Content-Type, filename extension)
_FORMATS = {
    "audio/ogg": ("audio/ogg", "ogg"),
    "audio/opus": ("audio/ogg", "ogg"),
    "audio/mpeg": ("audio/mpeg", "mp3"),
    "audio/mp4": ("audio/mp4", "m4a"),
    "audio/x-m4a": ("audio/mp4", "m4a"),
    "audio/wav": ("audio/wav", "wav"),
    "audio/webm": ("audio/webm", "webm"),
}
# Whisper has no Cameroonian Pidgin code; English is the closest.
_LANGUAGES = {"fr": "fr", "en": "en", "pcm": "en"}


def _format(mimetype: str) -> tuple[str, str]:
    # The mimetype comes from the webhook (untrusted): never forward the raw string, or a CRLF
    # in it would inject into the multipart headers.
    base = mimetype.split(";", 1)[0].strip().lower()
    return _FORMATS.get(base, _FORMATS[DEFAULT_TYPE])


def _segment_confidence(logprob: Any) -> float:
    value = float(logprob)
    if not math.isfinite(value):
        return 0.0
    # A log-probability above 0 is bogus; clamping first also avoids exp() overflow.
    return math.exp(min(0.0, value))


def _confidence(text: str, segments: list[Any]) -> float:
    if not segments:
        return 0.5 if text else 0.0
    values = [_segment_confidence(s["avg_logprob"]) for s in segments]
    return min(1.0, max(0.0, sum(values) / len(values)))


def _parse(payload: Any) -> Transcript:
    text = payload["text"].strip()
    language = payload.get("language") or ""
    if not isinstance(language, str):
        raise TypeError("language")
    segments = payload.get("segments") or []
    return Transcript(text=text, language=language, confidence=_confidence(text, segments))


class GroqWhisper:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = settings.GROQ_API_KEY if api_key is None else api_key
        self._base_url = (base_url or settings.GROQ_BASE_URL).rstrip("/")
        self._transport = transport

    def transcribe(
        self, audio: bytes, mimetype: str, language_hint: str | None = None
    ) -> Transcript:
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            return Transcript()
        model = settings.SPEECH_MODEL
        data = {"model": model, "response_format": "verbose_json", "temperature": "0"}
        language = _LANGUAGES.get(language_hint or "")
        if language:
            data["language"] = language
        # Callers pass webhook data; a missing mimetype must not make transcribe raise.
        content_type, extension = _format(mimetype if isinstance(mimetype, str) else "")
        started = time.monotonic()
        error: str | None = None
        transcript = Transcript()
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
                response = client.post(
                    f"{self._base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data=data,
                    files={"file": (f"audio.{extension}", audio, content_type)},
                )
                response.raise_for_status()
                transcript = _parse(response.json())
        except httpx.HTTPStatusError as exc:
            error = f"HTTPStatusError:{exc.response.status_code}"
        except Exception as exc:  # noqa: BLE001 - STT must never raise into the conversation flow
            error = type(exc).__name__
        if error:
            logger.warning("stt failed: %s", error)  # class and status only, never content
        try:
            record_call(
                purpose=PURPOSE,
                model=model,
                prompt_version="",
                latency_ms=int((time.monotonic() - started) * 1000),
                error=error,
            )
        except Exception as exc:  # noqa: BLE001 - a logging DB error must not lose the transcript
            logger.warning("stt call log failed: %s", type(exc).__name__)
        return transcript
