import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "tchekam"


def test_removed_provider_adapters_cannot_return():
    assert not (SRC / "ai/anthropic_client.py").exists()
    assert not (SRC / "speech/groq.py").exists()
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"ANTHROPIC_API_KEY|GROQ_API_KEY|import anthropic", source), path


def test_provider_sdks_stay_inside_enumerated_adapters():
    allowed = {
        "ai/openrouter_client.py",
        "ai/agent/models.py",
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
