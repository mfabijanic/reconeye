from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0004_merge_20260530_2140"),
    ]

    operations = [
        migrations.AlterField(
            model_name="camera",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("INSECAM", "Insecam"),
                    ("WHATSUPCAMS", "WhatsUpCams"),
                    ("WINDY", "Windy"),
                    ("GO2RTC", "go2rtc"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
