from django.apps import AppConfig


class AiConfig(AppConfig):
    name = "tchekam.ai"
    label = "ai"

    def ready(self):
        from django.db.models.signals import post_save, pre_delete, pre_save

        from tchekam.conversations.models import BotUser

        from .agent import tasks  # noqa: F401
        from .agent.retention import before_user_delete, before_user_save, control_saved
        from .models import AgentControl

        pre_delete.connect(before_user_delete, sender=BotUser, dispatch_uid="agent.erase")
        pre_save.connect(before_user_save, sender=BotUser, dispatch_uid="agent.block")
        post_save.connect(control_saved, sender=AgentControl, dispatch_uid="agent.kill_switch")
