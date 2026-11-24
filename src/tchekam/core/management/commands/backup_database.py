from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tchekam.core import backup
from tchekam.core.storage import get_object_store


class Command(BaseCommand):
    help = "Dump the database with pg_dump and upload it to the object store (backups/)."

    def handle(self, *args, **options):
        try:
            key = backup.create_backup(get_object_store(), now=timezone.now())
        except backup.BackupError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f"Backup stored as {key}")
