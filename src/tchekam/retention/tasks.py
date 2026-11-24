"""Retention jobs: the nightly run and the training-sample copy and deletion."""

from tchekam.core.tasks import register

from . import training
from .run import run_retention

# 02:00 in Cameroon (ADR-013), a quiet hour. Africa/Douala has no daylight saving time.
NIGHTLY_CRON = "0 2 * * *"
NIGHTLY_TZ = "Africa/Douala"


@register("retention.run", cron=NIGHTLY_CRON, tzinfo=NIGHTLY_TZ)
def nightly(timestamp: int | None = None) -> None:
    run_retention()


@register("retention.copy_training_samples")
def copy_training_samples(report_id: int) -> None:
    training.copy_samples(report_id)


@register("retention.delete_training_samples")
def delete_training_samples(user_id: int) -> None:
    training.delete_samples(user_id)
