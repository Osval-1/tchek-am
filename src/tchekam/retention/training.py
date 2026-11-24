"""Training copies of voice notes (ADR-013): made at decision time, deleted on STOP TRAINING.

A copy is made only while both the voice evidence and the user are opted in; it lives under
the `training/` prefix and outlives the report's own retention. STOP TRAINING withdraws the
consent inside the conversation lock and queues the blob deletion as a job (ADR-017: no
storage calls under the lock). A sample of a user on legal hold is kept until the hold is
released; the nightly run then deletes it.
"""

import logging
from typing import Any

from django.db import IntegrityError, transaction

from tchekam.conversations.models import BotUser
from tchekam.conversations.router import Context, Reply, register_intent
from tchekam.core.storage import get_object_store, new_key
from tchekam.core.tasks import enqueue
from tchekam.i18n import t
from tchekam.reports.models import Evidence, Report

from .hold import held_users
from .models import TrainingSample

logger = logging.getLogger(__name__)

INTENT = "training_opt_out"
DECIDED = frozenset({Report.Status.APPROVED, Report.Status.REJECTED})
_LANGS = ("fr", "en", "pcm")


def on_report_decided(sender: Any, report: Report, to_status: str, **kwargs: Any) -> None:
    """report_status_changed (after commit): queue the copy, never raising into the decision."""
    if to_status not in DECIDED:
        return
    try:
        enqueue("retention.copy_training_samples", report_id=report.pk)
    except Exception as exc:  # noqa: BLE001  a missed copy must not fail a moderation decision
        logger.warning("retention.training: copy not queued: %s", type(exc).__name__)


def copy_samples(report_id: int) -> int:
    """Copy the report's opted-in voice notes not copied yet. Returns how many were made."""
    report = Report.objects.select_related("reporter").filter(pk=report_id).first()
    if report is None or report.reporter is None or not report.reporter.training_opt_in:
        return 0
    voices = Evidence.objects.filter(
        report=report,
        kind=Evidence.Kind.VOICE,
        training_opt_in=True,
        training_sample__isnull=True,
    )
    made = 0
    for voice in voices:
        try:
            made += _copy(voice, report.reporter_id)
        except Exception as exc:  # noqa: BLE001  one unreadable file must not stop the others
            logger.warning("retention.training: copy failed: %s", type(exc).__name__)
    return made


def _copy(voice: Evidence, user_id: int) -> int:
    store = get_object_store()
    key = store.put(new_key("training"), store.get(voice.object_key), voice.mimetype)
    kept = False
    try:
        with transaction.atomic():
            # Locked so a STOP TRAINING committing meanwhile is seen: either it deletes this
            # sample, or this copy sees the withdrawal.
            owner = BotUser.objects.select_for_update().get(pk=user_id)
            if owner.training_opt_in:
                TrainingSample.objects.create(
                    user=owner,
                    evidence=voice,
                    audio_key=key,
                    mimetype=voice.mimetype,
                    transcript=voice.transcript,
                )
                kept = True
    except IntegrityError:
        pass  # a concurrent copy of the same evidence won
    finally:
        if not kept:
            store.delete(key)
    return int(kept)


def delete_samples(user_id: int) -> int:
    """Delete every sample of the user (blobs after commit), unless the user is on hold."""
    from .rules import delete_training_samples

    with transaction.atomic():
        rows = TrainingSample.objects.filter(user_id=user_id).exclude(user_id__in=held_users())
        return delete_training_samples(rows)


def handle_stop_training(ctx: Context) -> list[Reply]:
    """STOP TRAINING: withdraw consent now; the samples are deleted by a queued job."""
    user = ctx.user
    user.training_opt_in = False
    user.training_opt_in_asked = True  # the answer is now "no" for later reports too
    user.save(update_fields=["training_opt_in", "training_opt_in_asked"])
    Evidence.objects.filter(
        report__reporter=user, kind=Evidence.Kind.VOICE, training_opt_in=True
    ).update(training_opt_in=False)
    ctx.enqueue_after("retention.delete_training_samples", user_id=user.pk)
    if ctx.lang is None:  # a data-protection command: works before onboarding
        return [Reply("\n\n".join(t("training.opt_out.done", lang) for lang in _LANGS))]
    return [Reply(t("training.opt_out.done", ctx.lang))]


def register() -> None:
    register_intent(INTENT, handle_stop_training)
