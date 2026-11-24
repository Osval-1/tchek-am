from django.apps import AppConfig


class GroupsConfig(AppConfig):
    name = "tchekam.groups"
    label = "groups"

    def ready(self) -> None:
        # groups depends on messaging and conversations (not the reverse), so it plugs in here.
        from . import intake, optout

        intake.register()
        optout.register()
