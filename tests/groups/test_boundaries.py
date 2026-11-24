import dataclasses
import re
from pathlib import Path

from tchekam.imaging.search import Match

SRC = Path(__file__).resolve().parents[2] / "src" / "tchekam"
GROUPS = SRC / "groups"
# The bot never writes to a group or a group member (ADR-012): group code sends nothing at all.
SENDS = re.compile(r"\b(?:send_text|send_image|send_typing|send_to_user)\b")
IMPORTS_GROUPS = re.compile(r"^\s*(?:from|import)\s+tchekam\.groups\b", re.MULTILINE)
# imaging stores the PartnerGroup reference; the import there is for type checking only.
TYPE_ONLY = {SRC / "imaging" / "ingest.py"}


def _sources(folder: Path) -> list[Path]:
    return [p for p in folder.rglob("*.py") if "migrations" not in p.parts]


def test_group_code_never_sends_messages():
    offenders = [
        str(p.relative_to(SRC)) for p in _sources(GROUPS) if SENDS.search(p.read_text("utf-8"))
    ]

    assert offenders == []


def test_nothing_else_depends_on_the_groups_app():
    offenders = [
        str(p.relative_to(SRC))
        for p in _sources(SRC)
        if GROUPS not in p.parents
        and p not in TYPE_ONLY
        and IMPORTS_GROUPS.search(p.read_text("utf-8"))
    ]

    assert offenders == []


def test_type_only_import_is_really_type_only():
    source = (SRC / "imaging" / "ingest.py").read_text("utf-8")
    block = source.split("if TYPE_CHECKING:", 1)[1].split("\n\n", 1)[0]

    assert "tchekam.groups" in block
    assert "tchekam.groups" not in source.replace(block, "")


def test_scans_real_files():
    assert (GROUPS / "intake.py").exists()
    assert SENDS.search("channel.send_text(to, text)")


def test_search_matches_carry_no_group():
    fields = {f.name for f in dataclasses.fields(Match)}

    assert not any("group" in name for name in fields)
