import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "tchekam"
ALLOWED = SRC / "ai" / "anthropic_client.py"
FORBIDDEN = re.compile(r"^\s*(?:import\s+anthropic\b|from\s+anthropic\b)", re.MULTILINE)


def test_only_the_anthropic_adapter_imports_the_sdk():
    scanned = [*SRC.rglob("*.py"), *(ROOT / "evals").rglob("*.py")]
    offenders = [
        str(path.relative_to(ROOT))
        for path in scanned
        if path != ALLOWED and FORBIDDEN.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_boundary_check_scans_real_files():
    # Guard against a path bug making the test above pass vacuously.
    assert FORBIDDEN.search(ALLOWED.read_text(encoding="utf-8"))
