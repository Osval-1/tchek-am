from django.apps import AppConfig


class AppealsConfig(AppConfig):
    name = "tchekam.appeals"
    label = "appeals"

    def ready(self) -> None:
        # appeals depends on reputation and conversations (not the reverse), so everything is
        # plugged in from here.
        from tchekam.reputation import appeals_hook

        from . import tasks  # noqa: F401  # registers the appeals.* tasks
        from .flow import register
        from .notify import register as register_notify
        from .provider import appeal_state

        appeals_hook.set_provider(appeal_state)
        register()
        register_notify()
