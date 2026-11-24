"""Studio export with synthetic services only. Importing/invoking it never opens a database."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
if os.environ.get("DJANGO_SETTINGS_MODULE", "tchekam.settings.test") != "tchekam.settings.test":
    raise RuntimeError("Synthetic graph requires test settings.")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tchekam.settings.test")

import django

django.setup()

from langchain.agents import create_agent  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from tchekam.ai.agent.context import RunContext, TrustedResult  # noqa: E402
from tchekam.ai.agent.graph import PROMPT, build_graph  # noqa: E402
from tchekam.ai.agent.middleware import EnforcementMiddleware  # noqa: E402
from tchekam.ai.agent.models import fake_model  # noqa: E402
from tchekam.ai.agent.schemas import AgentDenied  # noqa: E402
from tchekam.ai.agent.tools import definitions  # noqa: E402
from tchekam.i18n import t  # noqa: E402


class SyntheticServices:
    def __init__(self):
        self.history, self.deliveries, self.audit = [], [], []

    def authorize(self, ctx):
        ctx.check_deadline()
        return SimpleNamespace(fence=ctx.fence)

    def owned_message(self, run):
        return SimpleNamespace(kind="text", text="Please check 677123456")

    def load_memory(self, ctx):
        return list(self.history)

    def complete(self, ctx, state):
        self.history.append({"role": "assistant", "action": state["action"].model_dump()})
        self.deliveries.extend(state["replies"])
        return True

    def publish(self, ctx):
        pass  # fake transport records deliveries in memory, never sends to a recipient

    def discard(self, ctx):
        self.deliveries.clear()

    def consume(self, ctx, counter):
        count = getattr(ctx, counter) + 1
        if count > (6 if counter == "model_calls" else 8):
            raise AgentDenied("call_limit")
        setattr(ctx, counter, count)

    def execute(self, ctx, name, arguments):
        self.authorize(ctx)
        self.consume(ctx, "tool_calls")
        if name != "check_number" or arguments != {"numbers": ["677123456"]}:
            raise AgentDenied("synthetic_tool")
        handle = "synthetic-number"
        ctx.results[handle] = TrustedResult(name, (t("check.number.green", "en"),))
        return handle

    def build_inner(self, ctx):
        return create_agent(
            ctx.model,
            tools=definitions(ctx, execute_fn=self.execute),
            system_prompt=PROMPT,
            middleware=[
                EnforcementMiddleware(
                    ctx,
                    authorize_fn=self.authorize,
                    consume_fn=self.consume,
                    audit_fn=lambda **kw: self.audit.append(kw),
                )
            ],
        )


def make_graph():
    services = SyntheticServices()
    ctx = RunContext(
        1,
        1,
        0,
        1,
        "en",
        sequence=1,
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
    return build_graph(ctx, services=services)


graph = make_graph()
