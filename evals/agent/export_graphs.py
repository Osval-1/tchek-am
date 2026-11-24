"""Export actual compiled outer and inner graphs with synthetic services, never provider calls."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from tchekam.ai.agent.context import RunContext  # noqa: E402
from tchekam.ai.agent.development import SyntheticServices, make_graph  # noqa: E402
from tchekam.ai.agent.models import fake_model  # noqa: E402


def main():
    output = ROOT / "docs/features/tchek-am-agent/graphs"
    output.mkdir(exist_ok=True)
    ctx = RunContext(1, 1, 0, 1, "en", model=fake_model())
    graphs = {"outer": make_graph(), "inner": SyntheticServices().build_inner(ctx)}
    for name, graph in graphs.items():
        (output / f"{name}.mmd").write_text(
            graph.get_graph(xray=True).draw_mermaid(), encoding="utf-8"
        )
    print("Exported compiled outer and inner graphs (synthetic, no network).")


if __name__ == "__main__":
    main()
