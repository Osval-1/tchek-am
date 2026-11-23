"""The speech-to-text boundary: everything outside this app transcribes through here."""

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings


@dataclass(frozen=True)
class Transcript:
    """`language` is the provider's own name (Groq says "french"), not our fr/en/pcm codes."""

    text: str = ""
    language: str = ""
    confidence: float = 0.0


class SpeechToText(Protocol):
    def transcribe(
        self, audio: bytes, mimetype: str, language_hint: str | None = None
    ) -> Transcript:
        """Never raises for provider failures; returns an empty Transcript instead."""
        ...


def get_speech_to_text() -> SpeechToText:
    backend = settings.SPEECH_BACKEND
    if backend == "fake":
        from .fake import FakeSpeechToText

        return FakeSpeechToText.instance()
    if backend == "groq":
        # Lazy so this factory stays the only place that names the provider adapter.
        from .groq import GroqWhisper

        return GroqWhisper()
    raise ValueError(f"Unknown SPEECH_BACKEND: {backend!r}")
