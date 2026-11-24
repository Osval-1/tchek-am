import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "tchekam"
IMAGING = SRC / "imaging"
SETTINGS = SRC / "settings"
ADAPTER = IMAGING / "serpapi.py"
ALLOWED = {ADAPTER, IMAGING / "web.py"}
# Settings may hold SERPAPI_* values; only imaging/{web,serpapi}.py may name the adapter or host.
FORBIDDEN = re.compile(r"SerpApiLensProvider|imaging\.serpapi|from \.serpapi|serpapi\.com")


def test_only_imaging_web_modules_know_serpapi():
    scanned = [*SRC.rglob("*.py"), *(ROOT / "evals").rglob("*.py")]
    offenders = [
        str(path.relative_to(ROOT))
        for path in scanned
        if path not in ALLOWED
        and path.parent != SETTINGS
        and FORBIDDEN.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_inside_imaging_only_the_factory_imports_the_adapter():
    importers = [
        p.name
        for p in IMAGING.glob("*.py")
        if p != ADAPTER and re.search(r"from \.serpapi|imaging\.serpapi", p.read_text("utf-8"))
    ]
    assert importers == ["web.py"]


def test_boundary_check_scans_real_files():
    # Guard against a path bug making the tests above pass vacuously.
    assert len(list(SRC.rglob("*.py"))) > 20
    assert re.search(r"class SerpApiLensProvider", ADAPTER.read_text(encoding="utf-8"))
    assert FORBIDDEN.search((IMAGING / "web.py").read_text(encoding="utf-8"))
