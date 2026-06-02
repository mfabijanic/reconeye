from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class SourceType(models.TextChoices):
    INSECAM = "INSECAM", "Insecam"
    WHATSUPCAMS = "WHATSUPCAMS", "WhatsUpCams"
    WINDY = "WINDY", "Windy"
    GO2RTC = "GO2RTC", "go2rtc"


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


class MapUISettings(models.Model):
    """Singleton settings for map UX behavior, editable in Django admin."""

    disable_clustering_at_zoom = models.PositiveSmallIntegerField(
        default=8,
        validators=[MinValueValidator(2), MaxValueValidator(18)],
        help_text="At or above this zoom level, clusters expand into individual markers.",
    )
    marker_limit = models.PositiveIntegerField(
        default=1500,
        validators=[MinValueValidator(100), MaxValueValidator(5000)],
        help_text="Maximum number of markers returned per map request.",
    )
    status_stale_minutes = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1), MaxValueValidator(1440)],
        help_text="Status older than this many minutes is shown as stale.",
    )
    popup_close_on_mouseout = models.BooleanField(
        default=True,
        help_text="Auto-close marker popup when pointer leaves marker.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Map UI Settings"
        verbose_name_plural = "Map UI Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "MapUISettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return "Map UI Settings"


class Go2RTCInstance(models.Model):
    class LastSyncStatus(models.TextChoices):
        NEVER = "NEVER", "Never"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    name = models.CharField(max_length=120, unique=True)
    scheme = models.CharField(max_length=8, default="http")
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=1984)
    is_active = models.BooleanField(default=True, db_index=True)

    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(
        max_length=12,
        choices=LastSyncStatus.choices,
        default=LastSyncStatus.NEVER,
        db_index=True,
    )
    last_sync_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "go2rtc Instance"
        verbose_name_plural = "go2rtc Instances"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "name"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.base_url})"

    @property
    def base_url(self) -> str:
        scheme = (self.scheme or "http").strip().lower() or "http"
        host = (self.host or "").strip()
        return f"{scheme}://{host}:{self.port}".rstrip("/")


class Go2RTCConfigSnapshot(models.Model):
    instance = models.ForeignKey(
        Go2RTCInstance,
        on_delete=models.CASCADE,
        related_name="config_snapshots",
    )
    config_payload = models.JSONField(default=dict)
    config_hash = models.CharField(max_length=64, blank=True, db_index=True)
    is_changed = models.BooleanField(default=False, db_index=True)
    change_summary = models.JSONField(default=dict)
    fetched_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "go2rtc Config Snapshot"
        verbose_name_plural = "go2rtc Config Snapshots"
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["instance", "-fetched_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.instance.name} @ {self.fetched_at:%Y-%m-%d %H:%M:%S}"


class Go2RTCStream(models.Model):
    instance = models.ForeignKey(
        Go2RTCInstance,
        on_delete=models.CASCADE,
        related_name="streams",
    )
    stream_name = models.CharField(max_length=255)
    producers_count = models.PositiveIntegerField(default=0)
    consumers_count = models.PositiveIntegerField(default=0)
    stream_payload = models.JSONField(default=dict)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name = "go2rtc Stream"
        verbose_name_plural = "go2rtc Streams"
        ordering = ["stream_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "stream_name"],
                name="uniq_go2rtc_stream_per_instance",
            )
        ]
        indexes = [
            models.Index(fields=["instance", "stream_name"]),
            models.Index(fields=["instance", "-last_seen_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.instance.name}: {self.stream_name}"
