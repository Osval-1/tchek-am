from typing import Any

from .base import Transcript


class FakeSpeechToText:
    """Canned transcripts for tests and offline runs, consumed in order.

    With nothing queued it returns an empty transcript, like a real failure would.
    """

    _instance: "FakeSpeechToText | None" = None

    def __init__(self) -> None:
        self.reset()

    @classmethod
    def instance(cls) -> "FakeSpeechToText":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reset(self) -> None:
        self.transcripts: list[Transcript] = []
        self.calls: list[dict[str, Any]] = []

    def transcribe(
        self, audio: bytes, mimetype: str, language_hint: str | None = None
    ) -> Transcript:
        self.calls.append({"audio": audio, "mimetype": mimetype, "language_hint": language_hint})
        return self.transcripts.pop(0) if self.transcripts else Transcript()
