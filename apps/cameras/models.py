from __future__ import annotations

from django.db import models
from django.utils import timezone


class SourceType(models.TextChoices):
    INSECAM = "INSECAM", "Insecam"
    WHATSUPCAMS = "WHATSUPCAMS", "WhatsUpCams"


class Camera(models.Model):
    title = models.CharField(max_length=255, blank=True)
    source_type = models.CharField(max_length=20, choices=SourceType.choices, db_index=True)
    country = models.CharField(max_length=100, blank=True, db_index=True)
    country_code = models.CharField(max_length=2, blank=True, db_index=True)
    region = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    timezone = models.CharField(max_length=32, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)

    # URLs
    stream_url = models.URLField(max_length=1024, blank=True)
    preview_image = models.URLField(max_length=1024, blank=True)
    page_url = models.URLField(max_length=1024, blank=True)

    # Status
    is_online = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    # Metadata
    has_partial_metadata = models.BooleanField(default=False)
    source_payload = models.JSONField(default=dict)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Camera"
        verbose_name_plural = "Cameras"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source_type", "is_online"]),
            models.Index(fields=["country", "city"]),
            models.Index(fields=["country_code", "source_type"]),
        ]

    def __str__(self) -> str:
        return self.title or f"Camera #{self.pk}"

    def mark_online(self) -> None:
        self.is_online = True
        self.last_checked = timezone.now()
        self.save(update_fields=["is_online", "last_checked", "updated_at"])

    def mark_offline(self) -> None:
        self.is_online = False
        self.last_checked = timezone.now()
        self.save(update_fields=["is_online", "last_checked", "updated_at"])


class CameraCheckLog(models.Model):
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="check_logs")
    checked_at = models.DateTimeField(auto_now_add=True)
    response_time_ms = models.IntegerField(null=True, blank=True)
    is_online = models.BooleanField()
    error_message = models.TextField(blank=True)

    class Meta:
        verbose_name = "Camera Check Log"
        verbose_name_plural = "Camera Check Logs"
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["camera", "checked_at"]),
        ]

    def __str__(self) -> str:
        status = "online" if self.is_online else "offline"
        return f"{self.camera} — {status} @ {self.checked_at:%Y-%m-%d %H:%M}"
