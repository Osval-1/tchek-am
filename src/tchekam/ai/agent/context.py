from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from typing import Any

from .schemas import AgentDenied


@dataclass(frozen=True)
class TrustedResult:
    operation: str
    texts: tuple[str, ...] = ()
    transition: str = ""


@dataclass
class RunContext:
    """Server-created, run-local authority. Never populated from model JSON."""

    run_id: int
    user_id: int
    generation: int
    fence: int
    lang: str
    sequence: int = 0
    model: Any = None
    model_resources: list[Any] = field(default_factory=list)
    tracer: Any = None
    deadline: float = field(default_factory=lambda: monotonic() + 60)
    model_calls: int = 0
    tool_calls: int = 0
    vision_calls: int = 0
    stt_calls: int = 0
    transcript: str = ""
    results: dict[str, TrustedResult] = field(default_factory=dict)
    staged: str = ""
    proposed_action: Any = None
    denial_code: str = ""
    tool_lock: Any = field(default_factory=RLock)

    def check_deadline(self):
        if monotonic() >= self.deadline:
            raise AgentDenied("deadline")
