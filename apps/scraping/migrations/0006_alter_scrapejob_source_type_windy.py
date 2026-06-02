from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scraping", "0005_rename_scraping_ge_provider_6ef8b8_idx_scraping_ge_provide_a9b049_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scrapejob",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("INSECAM", "Insecam"),
                    ("WHATSUPCAMS", "WhatsUpCams"),
                    ("WINDY", "Windy"),
                    ("GO2RTC", "go2rtc"),
                ],
                max_length=20,
            ),
        ),
    ]
