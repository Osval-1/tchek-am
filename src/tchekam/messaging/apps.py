from django.apps import AppConfig


class MessagingConfig(AppConfig):
    name = "tchekam.messaging"
    label = "messaging"

    def ready(self) -> None:
        # Register background tasks so the webhook can enqueue them by name.
        from . import tasks  # noqa: F401
