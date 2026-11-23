"""Versioned prompts: ai/prompts/<purpose>/v<N>.md, highest N wins."""

import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_VERSION_FILE = re.compile(r"v(\d+)\.md")


@lru_cache(maxsize=32)
def get_prompt(purpose: str) -> tuple[str, str]:
    """Return (text, version) for the latest prompt of a purpose, e.g. (..., "v2")."""
    folder = PROMPTS_DIR / purpose
    versions = {
        int(match.group(1)): path
        for path in (folder.glob("v*.md") if folder.is_dir() else [])
        if (match := _VERSION_FILE.fullmatch(path.name))
    }
    if not versions:
        raise LookupError(f"No prompt for purpose {purpose!r}")
    latest = max(versions)
    return versions[latest].read_text(encoding="utf-8").strip(), f"v{latest}"
