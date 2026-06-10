from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0012_go2rtcinstance_geo_city_go2rtcinstance_geo_country_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="go2rtcinstance",
            name="last_sync_status",
            field=models.CharField(
                choices=[
                    ("NEVER", "Never"),
                    ("SUCCESS", "Success"),
                    ("UNAUTHORIZED", "Unauthorized"),
                    ("FAILED", "Failed"),
                ],
                db_index=True,
                default="NEVER",
                max_length=12,
            ),
        ),
    ]
