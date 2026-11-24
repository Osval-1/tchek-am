from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tchekam.core.audit import audit
from tchekam.messaging.models import ChannelState


class Command(BaseCommand):
    help = "Switch the live WaSender session (primary or backup number). See docs/runbook.md."

    def add_arguments(self, parser):
        parser.add_argument("session", choices=[s.value for s in ChannelState.Session])

    def handle(self, *args, session, **options):
        if session == ChannelState.Session.BACKUP and not settings.WASENDER_BACKUP_API_KEY:
            raise CommandError("WASENDER_BACKUP_API_KEY is not set; refusing to switch.")
        if session == ChannelState.Session.PRIMARY and not settings.WASENDER_API_KEY:
            raise CommandError("WASENDER_API_KEY is not set; refusing to switch.")
        previous = ChannelState.current()
        ChannelState.switch(session)
        # Session names only: never keys or numbers.
        audit(None, "channel.switched", **{"from": previous, "to": session})
        self.stdout.write(f"Active WhatsApp session: {previous} -> {session}.")
