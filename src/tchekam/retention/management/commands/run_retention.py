from django.core.management.base import BaseCommand

from tchekam.retention.run import run_retention


class Command(BaseCommand):
    help = "Apply the retention schedule (ADR-013) now. --dry-run only counts what is due."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="count without deleting or auditing"
        )

    def handle(self, *args, dry_run: bool = False, **options):
        result = run_retention(dry_run=dry_run)
        if dry_run:
            self.stdout.write("dry run: nothing was changed")
        for name, count in result.counts.items():
            self.stdout.write(f"{name}: {count}")
        for name, error in result.errors.items():
            self.stderr.write(f"{name}: FAILED ({error})")
