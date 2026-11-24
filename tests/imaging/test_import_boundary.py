import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "tchekam"
ALLOWED = SRC / "imaging" / "embedder.py"
FORBIDDEN = re.compile(r"^\s*(?:import|from)\s+(?:torch|open_clip)\b", re.MULTILINE)


def test_only_the_imaging_embedder_imports_the_ml_stack():
    scanned = [*SRC.rglob("*.py"), *(ROOT / "evals").rglob("*.py")]
    offenders = [
        str(p.relative_to(ROOT))
        for p in scanned
        if p != ALLOWED and FORBIDDEN.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_boundary_check_scans_real_files():
    # Guard against a path bug making the test above pass vacuously.
    assert FORBIDDEN.search(ALLOWED.read_text(encoding="utf-8"))
