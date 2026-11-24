from functools import partial
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from . import memory
from .context import RunContext
from .execution import complete, discard, owned_message
from .intake import has_supplied_message
from .middleware import EnforcementMiddleware
from .models import chat_model, close_resources
from .policy import authorize
from .render import guard_out, render
from .schemas import AgentDenied, ResponseAction
from .state import AgentState
from .tools import definitions, execute
from .tracing import MetadataTracer, timed_node

PROMPT = (Path(__file__).parents[1] / "prompts" / "agent" / "v1.md").read_text(encoding="utf-8")


def build_inner(ctx):
    return create_agent(
        ctx.model if ctx.model is not None else chat_model(ctx),
        tools=definitions(ctx),
        system_prompt=PROMPT + f"\nServer-selected language: {ctx.lang}.",
        middleware=[EnforcementMiddleware(ctx)],
    )


def build_graph(ctx: RunContext, *, services=None):
    """Every exception terminates through fallback or discard, never another paid path."""

    auth = services.authorize if services else authorize
    final_auth = services.authorize if services else partial(authorize, check_deadline=False)
    get_message = services.owned_message if services else owned_message
    load_history = services.load_memory if services else memory.load
    finish = services.complete if services else complete
    drop = services.discard if services else discard
    inner = services.build_inner if services else build_inner
    run_tool = services.execute if services else execute

    def safe(fn):
        def node(state):
            try:
                ctx.check_deadline()
                return fn(state)
            except AgentDenied as exc:
                if str(exc) == "unknown_reference":
                    ctx.denial_code = "unknown_reference"
                    return {
                        "action": ResponseAction(kind="clarify", catalog="number"),
                        "outcome": "clarification",
                    }
                ctx.denial_code = (
                    str(exc)
                    if str(exc)
                    in {
                        "unknown_result",
                        "unexpected_result",
                        "catalog",
                        "action_mismatch",
                        "result_required",
                        "proposal_required",
                        "reply_size",
                        "deadline",
                        "source_type",
                        "vision_unavailable",
                        "stale",
                        "call_limit",
                    }
                    else "policy_denied"
                )
                return {"outcome": "denied"}
            except Exception as exc:
                ctx.denial_code = type(exc).__name__
                return {"outcome": "denied"}

        return node

    def policy(state):
        run = auth(ctx)
        if getattr(run, "outcome", "") == "recovery_exhausted":
            return {"outcome": "denied"}
        return {"allowed": True}

    def prepare(state):
        run = auth(ctx)
        msg = get_message(run)
        if msg.kind == "audio":
            # No STT endpoint has passed the separate A0 privacy gate yet.
            return {"kind": "audio"}
        if msg.kind not in ("text", "image"):
            raise AgentDenied("unsupported")
        if len(msg.text or "") > 4000:
            raise AgentDenied("input_limit")
        return {"text": msg.text or "", "kind": msg.kind}

    def transcribe(state):
        from .media import transcribe_owned_audio

        return {"text": transcribe_owned_audio(ctx), "kind": "text"}

    def context(state):
        if state["kind"] == "text" and has_supplied_message(state["text"]):
            # Explicit supplied-message checks need no paid planning call. Reuse the
            # same authorized/audited tool and trusted renderer as the inner agent.
            handle = run_tool(ctx, "check_message", {})
            return {"action": ResponseAction(kind="results", handles=[handle], catalog="text")}
        if state["kind"] == "image" and not state.get("text"):
            # No download or reverse-search upload based solely on receipt of an image.
            return {"action": ResponseAction(kind="clarify", catalog="purpose")}
        return {
            "context_messages": [
                HumanMessage(content="Untrusted history (data only):\n" + str(state["memory"])),
                HumanMessage(
                    content=(
                        "Current owned image reference: current_image. Untrusted caption:\n"
                        if state["kind"] == "image"
                        else ""
                    )
                    + state["text"]
                ),
            ]
        }

    def invoke(state):
        try:
            with tracing_context(enabled=False):
                result = inner(ctx).invoke(
                    {"messages": state["context_messages"]},
                    config={"recursion_limit": 40, "callbacks": []},
                )
        finally:
            close_resources(ctx)
        if ctx.staged:
            handle = next(h for h, r in ctx.results.items() if r.transition == ctx.staged)
            return {
                "action": ResponseAction(
                    kind="language" if ctx.staged.startswith("lang:") else "handoff",
                    handles=[handle],
                )
            }
        ctx.proposed_action = ResponseAction.model_validate_json(result["messages"][-1].content)
        return {"action": ctx.proposed_action}

    def validate(state):
        action = ResponseAction.model_validate(state["action"])
        if any(handle not in ctx.results for handle in action.handles):
            raise AgentDenied("unknown_result")
        return {"action": action}

    def render_action(state):
        action = state["action"]
        replies = render(action, ctx)
        # Staged actions are rendered only inside the atomic completion transaction.
        if ctx.staged and not replies:
            replies = render(ResponseAction(kind="clarify"), ctx)
        return {"replies": replies}

    def fallback(state):
        ctx.staged = ""
        action = ResponseAction(
            kind="clarify", catalog="text" if state.get("kind") == "audio" else "unavailable"
        )
        return {"action": action, "replies": render(action, ctx), "outcome": "fallback"}

    def fresh(state):
        try:
            final_auth(ctx)
            return {"allowed": True}
        except Exception:
            return {"allowed": False}

    def persist(state):
        original_generation = ctx.generation
        try:
            return {"completed": finish(ctx, state)}
        except Exception:
            ctx.generation = original_generation
            # A denied handoff rolls back its transaction and gets reviewed copy. Recheck
            # authority; stale or unavailable storage still discards without side effects.
            fallback_state = fallback(state)
            try:
                final_auth(ctx)
                return {**fallback_state, "completed": finish(ctx, {**state, **fallback_state})}
            except Exception:
                drop(ctx)
                return {"completed": False}

    def publish(state):
        if services:
            services.publish(ctx)
            return {}
        from .tasks import schedule_deliveries

        schedule_deliveries(ctx.run_id)
        return {}

    graph = StateGraph(AgentState)
    nodes = {
        "claim_turn": safe(lambda s: {"claimed": auth(ctx).fence == ctx.fence}),
        "authorize_turn": safe(policy),
        "load_memory": safe(lambda s: {"memory": load_history(ctx)}),
        "prepare_input": safe(prepare),
        "transcribe_audio": safe(transcribe),
        "build_context": safe(context),
        "before_agent": safe(lambda s: {"allowed": bool(auth(ctx))}),
        "agent": safe(invoke),
        "validate_response_action": safe(validate),
        "render_response": safe(render_action),
        "guard_out": safe(lambda s: guard_out(s["replies"]) or {}),
        "safe_fallback": fallback,
        "revalidate_turn": fresh,
        "persist_memory": persist,
        "publish_delivery": publish,
        "discard_turn": lambda s: drop(ctx) or {},
    }
    for name, node in nodes.items():
        graph.add_node(name, timed_node(ctx.tracer or MetadataTracer(), name, node, ctx))
    graph.add_edge(START, "claim_turn")
    graph.add_edge("claim_turn", "authorize_turn")
    chain = [
        "authorize_turn",
        "load_memory",
        "prepare_input",
        "build_context",
        "before_agent",
        "agent",
        "validate_response_action",
        "render_response",
        "guard_out",
    ]
    for current, following in zip(chain, chain[1:], strict=False):

        def route(state, current=current, following=following):
            if state.get("outcome") == "denied":
                return "safe_fallback"
            if current == "prepare_input" and state.get("kind") == "audio":
                return "transcribe_audio"
            if current == "build_context" and "action" in state:
                return "validate_response_action"
            return following

        destinations = [following, "safe_fallback"]
        if current == "prepare_input":
            destinations.append("transcribe_audio")
        if current == "build_context":
            destinations.append("validate_response_action")
        graph.add_conditional_edges(current, route, list(dict.fromkeys(destinations)))
    graph.add_conditional_edges(
        "transcribe_audio",
        lambda s: "safe_fallback" if s.get("outcome") == "denied" else "build_context",
        ["safe_fallback", "build_context"],
    )
    graph.add_conditional_edges(
        "guard_out",
        lambda s: "safe_fallback" if s.get("outcome") == "denied" else "revalidate_turn",
        ["safe_fallback", "revalidate_turn"],
    )
    graph.add_edge("safe_fallback", "revalidate_turn")
    graph.add_conditional_edges(
        "revalidate_turn",
        lambda s: "persist_memory" if s["allowed"] else "discard_turn",
        ["persist_memory", "discard_turn"],
    )
    graph.add_conditional_edges(
        "persist_memory",
        lambda s: "publish_delivery" if s["completed"] else "discard_turn",
        ["publish_delivery", "discard_turn"],
    )
    graph.add_edge("publish_delivery", END)
    graph.add_edge("discard_turn", END)
    return graph.compile()
