"""Rule engine for message red flags: keyword lists in fr, en and pcm.

Pure functions, no I/O. A flag is a hint about wording, never a statement about a person.
Matching is linear: phrases are literal, there are no nested quantifiers, and input is capped.
"""

import re
import unicodedata

from django.conf import settings

MAX_CHARS = 2000  # text beyond this is ignored, which also bounds worst-case matching time

UPFRONT_PAYMENT = "upfront_payment"
URGENCY = "urgency"
DELIVERY_INTERMEDIARY = "delivery_intermediary"
PAYEE_MISMATCH = "payee_mismatch"
REFUSES_COD_OR_MEETING = "refuses_cod_or_meeting"
PRICE_TOO_LOW = "price_too_low"

# The fixed list shared with the LLM prompt; the order is the display priority.
FLAG_CODES = (
    UPFRONT_PAYMENT,
    URGENCY,
    DELIVERY_INTERMEDIARY,
    PAYEE_MISMATCH,
    REFUSES_COD_OR_MEETING,
    PRICE_TOO_LOW,
)

# Phrases are written normalised (lower case, no accents, apostrophes and hyphens as spaces).
# The pcm ones need native review.
_PHRASES: dict[str, list[str]] = {
    UPFRONT_PAYMENT: [
        "paye d abord",  # fr
        "payez d abord",
        "paiement d abord",
        "paiement integral avant",
        "paiement avant livraison",
        "envoyez l argent d abord",
        "full payment",  # en
        "pay first",
        "payment first",
        "pay in advance",
        "advance payment",
        "send money first",
        "pay before delivery",
        "pay me first",  # pcm
        "pay before i send",
        "send di money first",
        "pay full money first",
        "pay before dem deliver",
    ],
    URGENCY: [
        "aujourd hui seulement",  # fr
        "dernier article",
        "derniere piece",
        "offre limitee",
        "dernier jour",
        "only today",  # en
        "last one",
        "last piece",
        "limited offer",
        "hurry",
        "today only",
        "act now",
        "na today only",  # pcm
        "only one remain",
        "last one remain",
        "come quick quick",
        "e go finish today",
    ],
    DELIVERY_INTERMEDIARY: [
        "mon transporteur",  # fr
        "mon livreur",
        "mon representant",
        "mon coursier",
        "mon collegue va livrer",
        "my delivery guy",  # en
        "my delivery man",
        "my representative",
        "representative",
        "my agent will deliver",
        "my courier",
        "my driver will bring",
        "my delivery man go bring",  # pcm
        "my pikin go bring",
        "my person go bring",
        "my agent go bring",
        "my driver go bring",
    ],
    PAYEE_MISMATCH: [
        "au nom de ma femme",  # fr
        "au nom de mon frere",
        "au nom de mon cousin",
        "le compte est au nom de",
        "le nom sera different",
        "under my wife s name",  # en
        "under my brother s name",
        "different name",
        "name on the account is different",
        "send to my brother",
        "send to my cousin",
        "di name no be mine",  # pcm
        "send am to my brother",
        "send am to my sister",
        "di account na for my wife",
        "di name go show different",
    ],
    REFUSES_COD_OR_MEETING: [
        "pas de paiement a la livraison",  # fr
        "pas de paiement a la reception",
        "je ne peux pas me deplacer",
        "pas de rencontre",
        "je ne me deplace pas",
        "no cash on delivery",  # en
        "no pay on delivery",
        "cannot meet",
        "can t meet",
        "no meeting",
        "i no dey meet",  # pcm
        "no pay when dem deliver",
        "i no fit meet",
        "make we no meet",
    ],
}

_SEPARATORS = re.compile(r"[\W_]+")  # a run of punctuation and whitespace becomes one space
# "50000", "50 000", "50.000", "50k", "50 mille"; the lookarounds keep digits of longer numbers out.
_AMOUNT = re.compile(r"(?<![\d.,])(\d{1,3}(?:[ .,]\d{3})+|\d{1,9})(?:\s?(k|mille)(?!\w))?(?!\d)")
_MIN_PLAIN_AMOUNT = 1000  # smaller bare numbers are quantities or fragments, not prices


def normalise(text: str) -> str:
    """Cap, strip accents, lower-case and collapse separators, so matching ignores formatting."""
    decomposed = unicodedata.normalize("NFKD", text[:MAX_CHARS])
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    # Apostrophes (straight or curly) and hyphens become spaces: "d'abord" -> "d abord".
    return _SEPARATORS.sub(" ", plain).strip()


def _compile(phrases: list[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(p) for p in phrases)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)")


_PATTERNS = {code: _compile(phrases) for code, phrases in _PHRASES.items()}


def _amounts(text: str) -> list[int]:
    # Read from the raw text: normalise() would turn "50.000" into "50 000" and merge neighbours.
    found: list[int] = []
    for match in _AMOUNT.finditer(text.casefold()):
        raw, suffix = match.groups()
        value = int(re.sub(r"\D", "", raw))
        if suffix:
            value *= 1000
        elif value < _MIN_PLAIN_AMOUNT:
            continue
        found.append(value)
    return found


def _price_too_low(text: str, norm: str) -> bool:
    hints = settings.PRICE_HINTS
    prices = [p for item, p in hints.items() if _compile([normalise(item)]).search(norm)]
    if not prices:
        return False
    amounts = _amounts(text[:MAX_CHARS])
    return any(a < p * settings.PRICE_HINT_RATIO for p in prices for a in amounts)


def rule_flags(text: str) -> list[str]:
    """Flag codes the wording triggers, in FLAG_CODES order, without duplicates."""
    norm = normalise(text)
    hits = {code for code, pattern in _PATTERNS.items() if pattern.search(norm)}
    if _price_too_low(text, norm):
        hits.add(PRICE_TOO_LOW)
    return [code for code in FLAG_CODES if code in hits]
