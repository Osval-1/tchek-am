"""OpenRouter transcription with ZDR routing and no direct speech-provider key."""

import base64
import logging
import math
from time import monotonic
from uuid import uuid4

import httpx
from django.conf import settings

from tchekam.ai.client import record_call

from .base import Transcript

logger = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 25 * 1024 * 1024
_FORMATS = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/webm": "webm",
    "audio/flac": "flac",
    "audio/aac": "aac",
}
_LANGUAGES = {"fr": "fr", "en": "en", "pcm": "en"}


def _format(mimetype):
    base = mimetype.split(";", 1)[0].strip().lower() if isinstance(mimetype, str) else ""
    return _FORMATS.get(base, "ogg")


def _parse(payload):
    text = payload["text"].strip()
    language = payload.get("language") or ""
    if not isinstance(language, str):
        raise TypeError("language")
    values = []
    for segment in payload.get("segments") or []:
        if "avg_logprob" in segment:
            value = float(segment["avg_logprob"])
            values.append(math.exp(min(0.0, value)) if math.isfinite(value) else 0.0)
    confidence = sum(values) / len(values) if values else (0.5 if text else 0.0)
    return Transcript(text=text, language=language, confidence=confidence)


class OpenRouterSTT:
    def __init__(self, *, context=None, api_key=None, transport=None):
        self.context, self.api_key, self.transport = context, api_key, transport

    def transcribe(self, audio: bytes, mimetype: str, language_hint=None) -> Transcript:
        if not audio or len(audio) > min(MAX_AUDIO_BYTES, settings.SPEECH_MAX_AUDIO_BYTES):
            return Transcript()
        started, call_id = monotonic(), uuid4().hex
        ctx, reservation, actual_cost = self.context, None, None
        transcript, error = Transcript(), None
        tokens_in, tokens_out, request_id, serving_provider = 0, 0, "", ""
        timeout = settings.OPENROUTER_TIMEOUT_SECONDS
        try:
            key = settings.OPENROUTER_API_KEY if self.api_key is None else self.api_key
            if not key:
                raise ValueError("provider_configuration")
            if ctx:
                from tchekam.ai.agent.budget import reserve
                from tchekam.ai.agent.policy import authorize, consume, remaining

                authorize(ctx)
                consume(ctx, "stt_calls")
                consume(ctx, "model_calls")
                reservation = reserve(ctx, call_id, settings.SPEECH_MAX_COST_MICROUSD)
                timeout = min(timeout, remaining(ctx))
            body = {
                "model": settings.SPEECH_MODEL,
                "input_audio": {
                    "data": base64.b64encode(audio).decode("ascii"),
                    "format": _format(mimetype),
                },
                "response_format": "verbose_json",
                "temperature": 0,
                # STT supports data-policy routing, but ignores only/order/ignore.
                # Never claim that this request enforces a chat endpoint allow-list.
                "provider": {"zdr": True, "data_collection": "deny"},
            }
            if language := _LANGUAGES.get(language_hint):
                body["language"] = language
            with httpx.Client(
                timeout=timeout,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    "https://openrouter.ai/api/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
            usage = payload.get("usage") or {}
            from tchekam.ai.agent.budget import billed_microusd

            actual_cost = billed_microusd(usage.get("cost"))
            tokens_in = max(0, int(usage.get("input_tokens", 0)))
            tokens_out = max(0, int(usage.get("output_tokens", 0)))
            request_id = str(payload.get("id") or response.headers.get("x-request-id") or "")[:100]
            serving_provider = str(payload.get("provider") or "")[:100]
            if payload.get("model", settings.SPEECH_MODEL) != settings.SPEECH_MODEL:
                raise ValueError("served_model")
            transcript = _parse(payload)
            if ctx:
                authorize(ctx)
        except httpx.HTTPStatusError as exc:
            error = f"HTTPStatusError:{exc.response.status_code}"
        except Exception as exc:
            error = type(exc).__name__
        finally:
            if reservation:
                from tchekam.ai.agent.budget import settle

                settle(reservation.pk, actual_cost)
            if error:
                transcript = Transcript()
                logger.warning("stt failed: %s", error)
            try:
                record_call(
                    purpose="stt",
                    model=settings.SPEECH_MODEL,
                    prompt_version="openrouter-stt-v1",
                    latency_ms=int((monotonic() - started) * 1000),
                    error=error,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    request_id=request_id,
                    serving_provider=serving_provider,
                    call_id=call_id,
                    agent_run_id=ctx.run_id if ctx else None,
                )
            except Exception as exc:
                if ctx:
                    raise  # mandatory agent audit must succeed before the transcript is used
                logger.warning("stt call log failed: %s", type(exc).__name__)
        return transcript
