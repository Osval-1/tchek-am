from typing import TYPE_CHECKING, Any

from django.apps import AppConfig

if TYPE_CHECKING:  # models cannot be imported before the app registry is ready
    from tchekam.reports.models import Report


class ReputationConfig(AppConfig):
    name = "tchekam.reputation"
    label = "reputation"

    def ready(self) -> None:
        from tchekam.reports.signals import report_status_changed

        report_status_changed.connect(_invalidate, dispatch_uid="reputation.invalidate_report")


def _invalidate(sender: type["Report"], report: "Report", **kwargs: Any) -> None:
    from .service import invalidate_report

    invalidate_report(report)
