"""Exercise the actual local OTLP receiver with the fake-only complete graph."""

import json
import os
import sys
from pathlib import Path
from time import monotonic, sleep

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main():
    env = dict(
        line.split("=", 1)
        for line in (ROOT / ".scratch/langfuse.env").read_text().splitlines()
        if "=" in line
    )
    os.environ.update(
        {
            "DJANGO_SETTINGS_MODULE": "tchekam.settings.test",
            "AGENT_TRACE_SYNTHETIC": "true",
            "LANGFUSE_BASE_URL": "http://localhost:3100",
            "LANGFUSE_PUBLIC_KEY": env["LF_PUBLIC_KEY"],
            "LANGFUSE_SECRET_KEY": env["LF_SECRET_KEY"],
        }
    )
    import django

    django.setup()
    from langchain_core.messages import AIMessage

    from tchekam.ai.agent.context import RunContext
    from tchekam.ai.agent.development import SyntheticServices
    from tchekam.ai.agent.graph import build_graph
    from tchekam.ai.agent.models import fake_model
    from tchekam.ai.agent.tracing import local_synthetic_tracer

    tracer = local_synthetic_tracer()
    if tracer.client is None:
        raise SystemExit("Local Langfuse authentication unavailable; smoke is incomplete.")
    ctx = RunContext(
        1,
        1,
        0,
        1,
        "en",
        sequence=1,
        tracer=tracer,
        model=fake_model(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "synthetic-call",
                            "name": "check_number",
                            "args": {"numbers": ["677123456"]},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content='{"kind":"results","handles":["synthetic-number"]}'),
            ]
        ),
    )
    trace_id = format(tracer.client.root.get_span_context().trace_id, "032x")
    state = build_graph(ctx, services=SyntheticServices()).invoke({"run_id": 1})
    tracer.flush()
    with httpx.Client(timeout=5, auth=(env["LF_PUBLIC_KEY"], env["LF_SECRET_KEY"])) as client:
        until, rows = monotonic() + 12, []
        while monotonic() < until:
            response = client.get(
                "http://localhost:3100/api/public/v2/observations", params={"traceId": trace_id}
            )
            if response.status_code == 200:
                rows = [
                    row for row in response.json().get("data", []) if row.get("traceId") == trace_id
                ]
            names = {row.get("name") for row in rows}
            if {
                "claim_turn",
                "load_memory",
                "check_number",
                "model_call",
                "persist_memory",
                "publish_delivery",
            } <= names:
                break
            sleep(0.5)
        received = (
            bool(rows)
            and {"check_number", "model_call", "persist_memory", "publish_delivery"} <= names
        )
        content_free = all(
            row.get("input") in (None, "", {}) and row.get("output") in (None, "", {})
            for row in rows
        )
    receipt = {
        "synthetic_only": True,
        "graph_completed": state.get("completed", False),
        "trace_id": trace_id,
        "observations_received": received,
        "read_status": response.status_code,
        "content_free": content_free,
        "observation_count": len(rows),
        "paid_calls": 0,
    }
    path = ROOT / ".scratch/agent-langfuse-smoke.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    return 0 if received and content_free else 1


if __name__ == "__main__":
    raise SystemExit(main())
