import time

import pytest

from tchekam.checks import redflags
from tchekam.checks.redflags import FLAG_CODES, rule_flags

# Three phrases per flag across fr, en and pcm (one each), as users would type them.
CASES = [
    ("upfront_payment", "Il faut que tu paye d'abord avant que j'envoie"),
    ("upfront_payment", "Full payment required before I ship"),
    ("upfront_payment", "Abeg pay me first, den I go send am"),
    ("urgency", "Prix valable aujourd'hui seulement !!"),
    ("urgency", "Hurry, ONLY TODAY at this price"),
    ("urgency", "E go finish today, no waste time"),
    ("delivery_intermediary", "Mon transporteur va te contacter"),
    ("delivery_intermediary", "My delivery guy will call you"),
    ("delivery_intermediary", "Wait, my delivery man go bring am"),
    ("payee_mismatch", "Le compte est au nom de ma femme"),
    ("payee_mismatch", "Send to my brother, the name on the account is different"),
    ("payee_mismatch", "Di name no be mine, na my cousin own"),
    ("refuses_cod_or_meeting", "Pas de paiement à la livraison, désolé"),
    ("refuses_cod_or_meeting", "No cash on delivery and I can't meet"),
    ("refuses_cod_or_meeting", "I no dey meet anybody, no pay when dem deliver"),
]


@pytest.mark.parametrize(("code", "text"), CASES)
def test_phrase_triggers_its_flag(code, text):
    assert code in rule_flags(text)


def test_every_code_has_at_least_three_cases_except_price():
    for code in FLAG_CODES:
        if code != "price_too_low":
            assert sum(1 for c, _ in CASES if c == code) >= 3


def test_each_flag_phrase_list_has_enough_languages():
    for code, phrases in redflags._PHRASES.items():
        assert len(phrases) >= 9, code


@pytest.mark.parametrize(
    "text",
    [
        "PAYE D’ABORD",  # curly apostrophe, upper case
        "paye   d'abord",  # extra whitespace
        "Aujourd’hui\nSEULEMENT",  # newline between words
        "Mon Représentant",  # accent
    ],
)
def test_matching_ignores_case_accents_and_whitespace(text):
    assert rule_flags(text)


def test_clean_text_has_no_flags():
    assert rule_flags("Bonjour, le téléphone est-il encore disponible ?") == []


def test_words_inside_other_words_do_not_match():
    assert rule_flags("unrepresentative sample") == []


@pytest.mark.parametrize(
    "text",
    [
        "iPhone 13 à 50000 FCFA",
        "Je vends iphone 13 pour 40 000 frs",
        "iPhone 13 na 50k only",
        "iphone 13 a 30.000",
    ],
)
def test_price_far_below_hint(text):
    assert "price_too_low" in rule_flags(text)


@pytest.mark.parametrize(
    "text",
    [
        "iPhone 13 à 240000 FCFA",
        "iPhone 13 à 150 000",  # discounted, not far below
        "J'ai 3 iphone 13 en stock",  # a quantity is not a price
        "Je vends un stylo à 500 FCFA",  # item without a hint
        "Appelez le 677 12 34 56 pour l'iPhone 13",  # a phone number is not an amount
    ],
)
def test_price_not_flagged(text):
    assert "price_too_low" not in rule_flags(text)


def test_price_hints_are_optional(settings):
    settings.PRICE_HINTS = {}
    assert rule_flags("iPhone 13 à 5000") == []


def test_flags_are_ordered_and_unique():
    flags = rule_flags("Only today! Pay first. Only today, pay first.")
    assert flags == ["upfront_payment", "urgency"]


@pytest.mark.parametrize(
    "text",
    [
        "pay " * 50000,
        "9" * 100000,
        "1 " * 100000,
        "iphone 13 " + "1.000" * 30000,
        "a" * 100000 + " paye d abord",  # beyond the cap, deliberately ignored
    ],
)
def test_adversarial_long_input_is_fast(text):
    start = time.perf_counter()
    rule_flags(text)
    assert time.perf_counter() - start < 1.0


def test_input_is_capped():
    text = "x " * (redflags.MAX_CHARS // 2) + "paye d'abord"
    assert rule_flags(text) == []
