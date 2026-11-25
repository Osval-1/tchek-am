import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "tchekam"
SPEECH = SRC / "speech"
SETTINGS = SRC / "settings"
ADAPTER = SPEECH / "openrouter.py"
# Only the speech app names the transcription adapter or endpoint.
FORBIDDEN = re.compile(
    r"OpenRouterSTT|speech\.openrouter\b|from \.openrouter\b|api/v1/audio/transcriptions"
)


def test_only_the_speech_app_knows_the_openrouter_adapter():
    scanned = [*SRC.rglob("*.py"), *(ROOT / "evals").rglob("*.py")]
    offenders = [
        str(path.relative_to(ROOT))
        for path in scanned
        if SPEECH not in path.parents
        and path.parent != SETTINGS  # the default base URL lives in settings
        and FORBIDDEN.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_inside_speech_only_the_factory_imports_the_adapter():
    importers = [
        p.name
        for p in SPEECH.glob("*.py")
        if p != ADAPTER
        and re.search(r"from \.openrouter|speech\.openrouter", p.read_text(encoding="utf-8"))
    ]

    assert importers == ["base.py"]


def test_boundary_check_scans_real_files():
    # Guard against a path bug making the tests above pass vacuously.
    assert len(list(SRC.rglob("*.py"))) > 20
    assert re.search(r"class OpenRouterSTT", ADAPTER.read_text(encoding="utf-8"))
    assert FORBIDDEN.search((SPEECH / "base.py").read_text(encoding="utf-8"))
