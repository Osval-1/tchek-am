from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResponseAction(StrictModel):
    """No field can contain model-authored user-facing text."""

    kind: Literal["results", "clarify", "advice", "handoff", "language"]
    handles: list[str] = Field(default_factory=list, max_length=10)
    catalog: Literal["number", "purpose", "text", "unavailable", "next_steps", "help"] = (
        "unavailable"
    )


class Numbers(StrictModel):
    numbers: list[str] = Field(min_length=1, max_length=10)


class Advice(StrictModel):
    topic: Literal["next_steps", "help"]


class Pattern(StrictModel):
    topic: Literal[
        "upfront_payment",
        "urgency",
        "delivery_intermediary",
        "payee_mismatch",
        "refuses_cod_or_meeting",
        "price_too_low",
    ]


class NameLookup(StrictModel):
    name: str = Field(min_length=2, max_length=100)
    operator: Literal["momo", "om", "unknown"]


class MediaReference(StrictModel):
    media_ref: Literal["current_image"]


class ImageRead(MediaReference):
    task: Literal["phone_numbers", "payment_amounts"]


class ImageObservation(StrictModel):
    numbers: list[str] = Field(max_length=10)
    amounts_xaf: list[int] = Field(max_length=10)
    uncertain: bool


class Handoff(StrictModel):
    intent: Literal["report", "appeal"]


class Language(StrictModel):
    lang: Literal["fr", "en", "pcm"]


class NoArgs(StrictModel):
    pass


class AgentDenied(Exception):
    """Content-free failure; the outer graph renders a reviewed fallback."""


class ModelUnavailable(AgentDenied):
    pass
