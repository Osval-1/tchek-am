import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "tchekam"
SPEECH = SRC / "speech"
SETTINGS = SRC / "settings"
ADAPTER = SPEECH / "groq.py"
# Settings may hold the GROQ_* values, but only the speech app may name the adapter or endpoint.
FORBIDDEN = re.compile(r"GroqWhisper|speech\.groq|from \.groq|api\.groq\.com")


def test_only_the_speech_app_knows_the_groq_adapter():
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
        if p != ADAPTER and re.search(r"from \.groq|speech\.groq", p.read_text(encoding="utf-8"))
    ]

    assert importers == ["base.py"]


def test_boundary_check_scans_real_files():
    # Guard against a path bug making the tests above pass vacuously.
    assert len(list(SRC.rglob("*.py"))) > 20
    assert re.search(r"class GroqWhisper", ADAPTER.read_text(encoding="utf-8"))
    assert FORBIDDEN.search((SPEECH / "base.py").read_text(encoding="utf-8"))
