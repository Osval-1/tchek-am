import ast
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


def test_provider_sdks_stay_inside_enumerated_adapters():
    allowed = {
        "ai/anthropic_client.py",
        "ai/openrouter_client.py",
        "ai/agent/models.py",
        "speech/groq.py",
        "speech/openrouter.py",
    }
    forbidden = {"anthropic", "openai", "openrouter", "langchain_openrouter", "langchain_openai"}
    offenders = []
    for path in [*SRC.rglob("*.py"), *(ROOT / "evals").rglob("*.py")]:
        relative = path.relative_to(SRC).as_posix() if path.is_relative_to(SRC) else str(path)
        if relative in allowed:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            if any(name.split(".")[0] in forbidden for name in names):
                offenders.append(relative)
    assert offenders == []
