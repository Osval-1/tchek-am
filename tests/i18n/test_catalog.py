import re
from pathlib import Path

import pytest

from tchekam.i18n import catalog, t

LANGS = ("fr", "en", "pcm")
BANNED = [
    "scammer",
    "scammers",
    "scam artist",
    "fraudeur",
    "fraudeurs",
    "arnaqueur",
    "arnaqueurs",
    "escroc",
    "escrocs",
    "419",
    "fraudster",
    "fraudsters",
    "fraud",
    "fraude",
]
BANNED_RE = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, BANNED)) + r")(?!\w)", re.IGNORECASE)


def test_every_key_has_all_three_languages():
    for key, entry in catalog.CATALOG.items():
        assert set(entry) == set(LANGS), key
        assert all(entry[lang].strip() for lang in LANGS), key


def test_no_banned_words_in_any_value():
    hits = [
        (key, lang)
        for key, entry in catalog.CATALOG.items()
        for lang, text in entry.items()
        if BANNED_RE.search(text)
    ]
    assert hits == []


def test_banned_regex_catches_and_spares():
    assert BANNED_RE.search("Un Arnaqueur!")
    assert BANNED_RE.search("code 419")
    assert BANNED_RE.search("Fraud alert")
    assert not BANNED_RE.search("Signaler une arnaque")
    assert not BANNED_RE.search("Report a scam: 4190 XAF")


def test_every_pidgin_value_is_marked_for_native_review():
    # Copy may live in catalog.py or in a catalog_*.py file merged into it.
    files = Path(catalog.__file__).parent.glob("catalog*.py")
    source = "\n".join(p.read_text(encoding="utf-8") for p in files)
    marked = [ln for ln in source.splitlines() if ln.endswith("# needs native review")]
    assert len(marked) == len(catalog.CATALOG)


def test_t_returns_requested_language():
    assert t("common.coming_soon", "en") != t("common.coming_soon", "fr")


def test_none_language_falls_back_to_french():
    assert t("common.coming_soon", None) == t("common.coming_soon", "fr")


def test_missing_language_falls_back_to_french(monkeypatch):
    monkeypatch.setitem(catalog.CATALOG, "x.only_fr", {"fr": "Bonjour"})
    assert t("x.only_fr", "pcm") == "Bonjour"
    assert t("x.only_fr", "en") == "Bonjour"


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        t("no.such.key", "fr")


def test_formatting_and_missing_argument_raises(monkeypatch):
    monkeypatch.setitem(catalog.CATALOG, "x.hello", {"fr": "Salut {name}"})
    assert t("x.hello", "fr", name="Ada") == "Salut Ada"
    with pytest.raises(KeyError):
        t("x.hello", "fr")
