from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # Creates the table for every DatabaseCache in settings.CACHES; a no-op for other backends
    # (test settings use LocMem) and when the table already exists.
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        # Reverse is a no-op: the cache table is disposable and outside Django's model state.
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
