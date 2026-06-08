from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0006_go2rtc_manager_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="Go2RTCGridProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "go2rtc Grid Profile",
                "verbose_name_plural": "go2rtc Grid Profiles",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Go2RTCGridItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stream_name", models.CharField(max_length=255)),
                ("title", models.CharField(blank=True, max_length=255)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("source_payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("instance", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="grid_items", to="cameras.go2rtcinstance")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="cameras.go2rtcgridprofile")),
            ],
            options={
                "verbose_name": "go2rtc Grid Item",
                "verbose_name_plural": "go2rtc Grid Items",
                "ordering": ["sort_order", "id"],
                "indexes": [
                    models.Index(fields=["profile", "is_active", "sort_order"], name="cameras_go2_profile_950191_idx"),
                    models.Index(fields=["instance", "stream_name"], name="cameras_go2_instan_4687b7_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("profile", "instance", "stream_name"), name="uniq_go2rtc_grid_item_per_profile_stream"),
                ],
            },
        ),
    ]
