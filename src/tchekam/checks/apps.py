from django.apps import AppConfig


class ChecksConfig(AppConfig):
    name = "tchekam.checks"
    label = "checks"

    def ready(self) -> None:
        # checks depends on conversations (not the reverse), so the intent is plugged in here.
        from . import number, photo

        number.register()
        photo.register()
