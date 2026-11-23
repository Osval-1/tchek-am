import unicodedata


def normalize_name(raw: str) -> str:
    """Upper-case, strip accents, collapse whitespace and trim."""
    decomposed = unicodedata.normalize("NFKD", raw)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(ascii_only.upper().split())


def _mask_word(word: str) -> str:
    if len(word) == 1:
        return word
    if "-" in word:
        head, _, rest = word.partition("-")
        return f"{head}-{rest[0]}***" if rest else word
    return f"{word[0]}***"


def mask_name(raw: str) -> str:
    """Mask a name for display, working on the normalised form.

    Rules, applied per whitespace-separated word:
    - a single-letter word is kept as is;
    - a hyphenated word keeps its first hyphen-part whole, then the first letter of the next
      part and "***" (e.g. "JEAN-PAUL" -> "JEAN-P***", "A-B" -> "A-B***");
    - any other word keeps its first letter and "***" (e.g. "MBARGA" -> "M***").
    """
    return " ".join(_mask_word(word) for word in normalize_name(raw).split())
