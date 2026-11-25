"""Message red flags: pasted message text -> flag codes chosen by the model.

Kept apart from the shared schemas so the purpose is self-contained. The model's free-text
explanations are parsed (the schema asks for them, which keeps its reasoning on-topic) but never
returned: callers show reviewed catalogue copy for each code instead.
"""

import re

from django.conf import settings
from pydantic import BaseModel

from .client import get_llm_client
from .registry import get_prompt

PURPOSE = "message_red_flags"
EFFORT = "low"
MAX_TOKENS = 1024
MAX_CHARS = 2000
_CLOSING_TAG = re.compile(r"</\s*message\s*>", re.IGNORECASE)


class RedFlagItem(BaseModel):
    code: str  # checked against the fixed list by the caller; an unknown code is dropped there
    explanation: str


class RedFlagResult(BaseModel):
    flags: list[RedFlagItem]


def llm_flag_codes(text: str, allowed: tuple[str, ...]) -> list[str] | None:
    """Flag codes the model found, restricted to `allowed`; None when the call failed.

    Never raises for model failures. The text goes to the LLM provider only, and is never logged.
    """
    system, version = get_prompt(PURPOSE)
    # Tags mark the untrusted part; a closing tag inside the text must not end the block early.
    body = _CLOSING_TAG.sub("< /message>", text[:MAX_CHARS])
    result = get_llm_client().structured(
        purpose=PURPOSE,
        model=settings.OPENROUTER_MODEL,
        system=system,
        user_content=[{"type": "text", "text": f"<message>\n{body}\n</message>"}],
        schema_model=RedFlagResult,
        effort=EFFORT,
        max_tokens=MAX_TOKENS,
        prompt_version=version,
    )
    if not result.ok or not isinstance(result.data, RedFlagResult):
        return None
    return [item.code for item in result.data.flags if item.code in allowed]
