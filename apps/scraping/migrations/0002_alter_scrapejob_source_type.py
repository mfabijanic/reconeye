from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scraping", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scrapejob",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("INSECAM", "Insecam"),
                    ("WHATSUPCAMS", "WhatsUpCams"),
                    ("GO2RTC", "go2rtc"),
                ],
                max_length=20,
            ),
        ),
    ]
