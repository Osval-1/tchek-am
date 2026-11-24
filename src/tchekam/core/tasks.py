import json
from collections.abc import Callable
from typing import Any

from django.conf import settings
from procrastinate.contrib.django import app

_REGISTRY: dict[str, Callable] = {}


class UnknownTaskError(KeyError):
    pass


def register(
    name: str, *, cron: str | None = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a function as a named task, runnable inline or via the Procrastinate worker.

    With `cron`, the worker also defers it on that schedule; such a function takes a leading
    `timestamp` argument (Procrastinate passes the scheduled time).
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if name in _REGISTRY:
            raise ValueError(f"Task {name!r} is already registered")
        _REGISTRY[name] = func
        task = app.task(name=name)(func)
        if cron is not None:
            app.periodic(cron=cron)(task)
        return func

    return decorator


def enqueue(
    name: str,
    *,
    schedule_in_seconds: int | None = None,
    queue: str | None = None,
    lock: str | None = None,
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
    if lock is not None:
        options["lock"] = lock  # jobs sharing a lock never run at the same time
        # Mutex: a job scheduled for later must not hold the lock and stall every other job on it.
        options["lock_mode"] = "mutex"
    app.configure_task(name=name, **options).defer(**kwargs)


# Monthly, 03:00 UTC on the 1st. The worker defers it (de-duplicated across workers).
@register("core.backup_database", cron="0 3 1 * *")
def backup_database(timestamp: int) -> None:
    # Imported here: storage and backup need Django settings, which tasks.py may load too early.
    from django.utils import timezone

    from tchekam.core import backup
    from tchekam.core.storage import get_object_store

    backup.create_backup(get_object_store(), now=timezone.now())
