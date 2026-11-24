from typing import NotRequired, TypedDict

from .schemas import ResponseAction


class AgentState(TypedDict):
    run_id: int
    claimed: NotRequired[bool]
    allowed: NotRequired[bool]
    memory: NotRequired[list[dict]]
    text: NotRequired[str]
    kind: NotRequired[str]
    context_messages: NotRequired[list]
    action: NotRequired[ResponseAction]
    replies: NotRequired[list[str]]
    outcome: NotRequired[str]
    completed: NotRequired[bool]
