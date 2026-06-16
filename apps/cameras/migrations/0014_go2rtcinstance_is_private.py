from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0013_alter_go2rtcinstance_last_sync_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="go2rtcinstance",
            name="is_private",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]