import json
from collections.abc import Callable
from typing import Any

from django.conf import settings
from procrastinate.contrib.django import app

_REGISTRY: dict[str, Callable] = {}


class UnknownTaskError(KeyError):
    pass


def register(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a function as a named task, runnable inline or via the Procrastinate worker."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if name in _REGISTRY:
            raise ValueError(f"Task {name!r} is already registered")
        _REGISTRY[name] = func
        app.task(name=name)(func)
        return func

    return decorator


def enqueue(
    name: str,
    *,
    schedule_in_seconds: int | None = None,
    queue: str | None = None,
    **kwargs: Any,
) -> None:
    func = _REGISTRY.get(name)
    if func is None:
        raise UnknownTaskError(name)
    if settings.TASKS_EAGER:
        # Round-trip through JSON so non-serialisable args fail in tests, not only in prod.
        func(**json.loads(json.dumps(kwargs)))
        return
    options: dict[str, Any] = {}
    if schedule_in_seconds is not None:
        options["schedule_in"] = {"seconds": schedule_in_seconds}
    if queue is not None:
        options["queue"] = queue
    # Resolve through the proxy at call time: tasks are registered on a pre-ready blueprint.
    app.configure_task(name=name, **options).defer(**kwargs)
