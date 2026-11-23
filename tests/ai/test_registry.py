import pytest

from tchekam.ai import registry


@pytest.fixture
def prompts(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "PROMPTS_DIR", tmp_path)
    registry.get_prompt.cache_clear()
    yield tmp_path
    registry.get_prompt.cache_clear()


def test_highest_version_wins_numerically(prompts):
    folder = prompts / "demo"
    folder.mkdir()
    (folder / "v1.md").write_text("one", encoding="utf-8")
    (folder / "v2.md").write_text("two", encoding="utf-8")
    (folder / "v10.md").write_text("ten\n", encoding="utf-8")
    (folder / "notes.md").write_text("ignored", encoding="utf-8")

    assert registry.get_prompt("demo") == ("ten", "v10")


def test_prompt_is_cached(prompts):
    folder = prompts / "demo"
    folder.mkdir()
    (folder / "v1.md").write_text("one", encoding="utf-8")
    registry.get_prompt("demo")
    (folder / "v2.md").write_text("two", encoding="utf-8")

    assert registry.get_prompt("demo") == ("one", "v1")


def test_unknown_purpose_raises(prompts):
    with pytest.raises(LookupError):
        registry.get_prompt("missing")


def test_shipped_extraction_prompt_loads():
    text, version = registry.get_prompt("evidence_extraction")

    assert version == "v1"
    assert "Orange Money" in text and "MTN MoMo" in text
    assert "payment_proof_candidate" in text
