from tchekam.i18n import t

from .context import RunContext
from .schemas import AgentDenied, ResponseAction

CATALOGS = {
    "number": "prompt.send_number",
    "purpose": "agent.image.purpose",
    "text": "prompt.expected_message",
    "unavailable": "common.coming_soon",
    "next_steps": "notify.next_steps",
    "help": "help.main",
}


def render(action: ResponseAction, ctx: RunContext) -> list[str]:
    if action.kind in ("results", "handoff", "language"):
        if not action.handles or len(set(action.handles)) != len(action.handles):
            raise AgentDenied("result_required")
        results = []
        for handle in action.handles:
            result = ctx.results.get(handle)
            if result is None:
                raise AgentDenied("unknown_result")
            if result.transition and action.kind not in ("handoff", "language"):
                raise AgentDenied("action_mismatch")
            results.extend(result.texts)
        if action.kind in ("handoff", "language") and not ctx.staged:
            raise AgentDenied("proposal_required")
        return results
    if action.handles:
        raise AgentDenied("unexpected_result")
    allowed = (
        ("next_steps", "help")
        if action.kind == "advice"
        else ("number", "purpose", "text", "unavailable")
    )
    if action.catalog not in allowed:
        raise AgentDenied("catalog")
    return [t(CATALOGS[action.catalog], ctx.lang)]


def guard_out(texts: list[str]) -> None:
    if not texts or len(texts) > 10 or any(not text or len(text) > 12000 for text in texts):
        raise AgentDenied("reply_size")
