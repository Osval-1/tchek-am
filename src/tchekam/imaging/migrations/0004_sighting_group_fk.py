"""Turn the ImageSighting.group_id placeholder into a real FK to groups.PartnerGroup.

The column stays `group_id` throughout: pin it as db_column (no-op), rename the field
(no-op, the column is pinned), then alter the type (adds the FK constraint and index, drops
the positive-integer check). Any existing value must point at a PartnerGroup; there is no
group data before Issue 20, so none exists.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("groups", "0001_initial"),
        ("imaging", "0003_web_search"),
    ]

    operations = [
        migrations.AlterField(
            model_name="imagesighting",
            name="group_id",
            field=models.PositiveBigIntegerField(blank=True, db_column="group_id", null=True),
        ),
        migrations.RenameField(model_name="imagesighting", old_name="group_id", new_name="group"),
        migrations.AlterField(
            model_name="imagesighting",
            name="group",
            field=models.ForeignKey(
                blank=True,
                db_column="group_id",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="groups.partnergroup",
            ),
        ),
    ]
