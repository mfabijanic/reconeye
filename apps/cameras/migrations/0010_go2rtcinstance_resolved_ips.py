# Generated for IP-based go2rtc instance auto-grouping.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0009_go2rtcinstance_path"),
    ]

    operations = [
        migrations.AddField(
            model_name="go2rtcinstance",
            name="resolved_ips",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "IP addresses the host (FQDN or literal IP) resolved to during "
                    "the last sync. A single FQDN may resolve to several IPs "
                    "(round-robin DNS); instances whose IP sets overlap are "
                    "auto-grouped together."
                ),
            ),
        ),
        migrations.AddField(
            model_name="go2rtcinstance",
            name="ips_resolved_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When resolved_ips was last refreshed.",
            ),
        ),
    ]
