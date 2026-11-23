import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "tchekam"
MESSAGING = SRC / "messaging"
FORBIDDEN = re.compile(r"tchekam\.messaging\.wasender|\bWaSenderChannel\b|from\s+\.+wasender\b")


def test_only_messaging_knows_about_wasender_channel():
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if MESSAGING not in path.parents and FORBIDDEN.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_boundary_check_scans_real_files():
    # Guard against a path bug making the test above pass vacuously.
    assert (MESSAGING / "wasender.py").exists()
    assert FORBIDDEN.search((MESSAGING / "channel.py").read_text(encoding="utf-8"))
