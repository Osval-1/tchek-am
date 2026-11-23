from django.db import migrations, models

from tchekam.reports.keys import reporter_key_for


def backfill_reporter_keys(apps, schema_editor):
    """Give reports created before this migration the key their reporter would get now."""
    Report = apps.get_model("reports", "Report")
    pending = Report.objects.using(schema_editor.connection.alias).filter(
        reporter__isnull=False, reporter_key=""
    )
    for report in pending.select_related("reporter").iterator():
        report.reporter_key = reporter_key_for(report.reporter.wa_phone)
        report.save(update_fields=["reporter_key"])


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="report",
            name="reporter_key",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        # Reports whose reporter was already erased cannot be recovered; they stay blank.
        migrations.RunPython(backfill_reporter_keys, migrations.RunPython.noop),
    ]
