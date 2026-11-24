"""Recognize explicit pasted-message checks without interpreting the pasted data."""

import re
import unicodedata

SEPARATOR = re.compile(r'[:\n\r«“"]')
REQUEST = re.compile(
    r"^\s*(?:(?:please|abeg|can you|could you|you fit|peux-tu|pouvez-vous|tu peux|merci de)\s+)?"
    r"(?:check|analyse|analyze|analyser|analysez|verifie|verifier|verifiez)\b"
    r"[^:\n]{0,160}\b(?:message|msg|texte|text|wetin)\b"
    r"|^\s*is this message\b[^:\n]{0,80}\b(?:suspicious|scam|safe)\b"
)
OTHER_TASK = re.compile(r"\b(?:number|numero|photo|image|report|signalement|appeal)\b|\d")


def has_supplied_message(text: str) -> bool:
    """Narrow shortcut: request prefix + delimiter + nonempty pasted text.

    Ambiguous and combined requests stay with the conversational planner. Only the
    prefix is inspected; instructions in the pasted portion cannot select tools.
    """
    boundary = SEPARATOR.search(text)
    if (
        boundary is None
        or boundary.start() > 240
        or not text[boundary.end() :].strip(' \t\r\n«»“”"')
    ):
        return False
    prefix = "".join(
        char
        for char in unicodedata.normalize("NFKD", text[: boundary.start()].casefold())
        if not unicodedata.combining(char)
    )
    return bool(REQUEST.search(prefix)) and not OTHER_TASK.search(prefix)
