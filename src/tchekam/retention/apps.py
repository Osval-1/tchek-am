from django.apps import AppConfig


class RetentionConfig(AppConfig):
    name = "tchekam.retention"
    label = "retention"

    def ready(self) -> None:
        # retention depends on every app that holds personal data, so it plugs itself in
        # here: reputation's trust seam, the user guards, the training copy on decisions and
        # the STOP TRAINING keyword. The only reverse dependency is the admin layer: the
        # reports, identifiers and conversations admins import retention.hold for the
        # legal-hold actions (admin modules load after every app is ready).
        from django.db.models.signals import post_save, pre_delete

        from tchekam.conversations.models import BotUser
        from tchekam.reports.signals import report_status_changed
        from tchekam.reputation import trust_hook

        from . import (
            tasks,  # noqa: F401  # registers the retention.* tasks
            training,
            trust,
        )

        trust_hook.set_provider(trust.trust_for_keys)
        pre_delete.connect(
            trust.before_user_delete, sender=BotUser, dispatch_uid="retention.user_delete"
        )
        post_save.connect(trust.seed_new_user, sender=BotUser, dispatch_uid="retention.user_seed")
        report_status_changed.connect(
            training.on_report_decided, dispatch_uid="retention.copy_training"
        )
        training.register()
