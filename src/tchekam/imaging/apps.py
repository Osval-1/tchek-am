from django.apps import AppConfig


class ImagingConfig(AppConfig):
    name = "tchekam.imaging"
    label = "imaging"

    def ready(self) -> None:
        from . import tasks  # noqa: F401  # registers imaging.embed
