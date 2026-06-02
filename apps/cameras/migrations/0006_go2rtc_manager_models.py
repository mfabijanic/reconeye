from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0005_alter_camera_source_type_windy"),
    ]

    operations = [
        migrations.CreateModel(
            name="Go2RTCInstance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("scheme", models.CharField(default="http", max_length=8)),
                ("host", models.CharField(max_length=255)),
                ("port", models.PositiveIntegerField(default=1984)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_sync_status",
                    models.CharField(
                        choices=[("NEVER", "Never"), ("SUCCESS", "Success"), ("FAILED", "Failed")],
                        db_index=True,
                        default="NEVER",
                        max_length=12,
                    ),
                ),
                ("last_sync_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "go2rtc Instance",
                "verbose_name_plural": "go2rtc Instances",
                "ordering": ["name"],
                "indexes": [models.Index(fields=["is_active", "name"], name="cameras_go2_is_acti_8f6d2f_idx")],
            },
        ),
        migrations.CreateModel(
            name="Go2RTCConfigSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("config_payload", models.JSONField(default=dict)),
                ("config_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                ("is_changed", models.BooleanField(db_index=True, default=False)),
                ("change_summary", models.JSONField(default=dict)),
                ("fetched_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "instance",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="config_snapshots", to="cameras.go2rtcinstance"),
                ),
            ],
            options={
                "verbose_name": "go2rtc Config Snapshot",
                "verbose_name_plural": "go2rtc Config Snapshots",
                "ordering": ["-fetched_at"],
                "indexes": [models.Index(fields=["instance", "-fetched_at"], name="cameras_go2_instan_7f8f91_idx")],
            },
        ),
        migrations.CreateModel(
            name="Go2RTCStream",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stream_name", models.CharField(max_length=255)),
                ("producers_count", models.PositiveIntegerField(default=0)),
                ("consumers_count", models.PositiveIntegerField(default=0)),
                ("stream_payload", models.JSONField(default=dict)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "instance",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="streams", to="cameras.go2rtcinstance"),
                ),
            ],
            options={
                "verbose_name": "go2rtc Stream",
                "verbose_name_plural": "go2rtc Streams",
                "ordering": ["stream_name"],
                "indexes": [
                    models.Index(fields=["instance", "stream_name"], name="cameras_go2_instan_191ab6_idx"),
                    models.Index(fields=["instance", "-last_seen_at"], name="cameras_go2_instan_6f1942_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("instance", "stream_name"), name="uniq_go2rtc_stream_per_instance")
                ],
            },
        ),
    ]
