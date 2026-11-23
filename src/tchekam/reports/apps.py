from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = "tchekam.reports"
    label = "reports"

    def ready(self) -> None:
        # reports depends on conversations (not the reverse), so the flow is plugged in here.
        from . import tasks  # noqa: F401  # registers reports.ingest_media and reports.extract
        from .flow import register

        register()
