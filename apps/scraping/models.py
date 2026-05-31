from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.cameras.models import SourceType


class ScrapeJobStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    RUNNING = "RUNNING", "Running"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


class ScrapeJob(models.Model):
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    target_country_code = models.CharField(max_length=2, blank=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=ScrapeJobStatus.choices,
        default=ScrapeJobStatus.PENDING,
        db_index=True,
    )
    celery_task_id = models.CharField(max_length=255, blank=True, db_index=True)

    # Lifecycle timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Progress counters
    total_found = models.IntegerField(default=0)
    total_processed = models.IntegerField(default=0)
    total_new = models.IntegerField(default=0)
    total_updated = models.IntegerField(default=0)

    # Error info
    error_message = models.TextField(blank=True)

    class Meta:
        verbose_name = "Scrape Job"
        verbose_name_plural = "Scrape Jobs"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        target = f" [{self.target_country_code}]" if self.target_country_code else ""
        return f"{self.get_source_type_display()}{target} — {self.status} ({self.created_at:%Y-%m-%d %H:%M})"

    @property
    def progress_pct(self) -> int:
        # For completed jobs that discovered no cameras, show finished state as 100%.
        if self.status == ScrapeJobStatus.SUCCESS and self.total_found == 0:
            return 100
        return min(100, round((self.total_processed / max(self.total_found, 1)) * 100))

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or timezone.now()
        return (end - self.started_at).total_seconds()

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            ScrapeJobStatus.SUCCESS,
            ScrapeJobStatus.FAILED,
            ScrapeJobStatus.CANCELLED,
        )

    def mark_running(self) -> None:
        self.status = ScrapeJobStatus.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def mark_success(self) -> None:
        self.status = ScrapeJobStatus.SUCCESS
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at"])

    def mark_failed(self, error: str = "") -> None:
        self.status = ScrapeJobStatus.FAILED
        self.finished_at = timezone.now()
        self.error_message = error
        self.save(update_fields=["status", "finished_at", "error_message"])

    def mark_cancelled(self, reason: str = "Cancelled by user") -> None:
        self.status = ScrapeJobStatus.CANCELLED
        self.finished_at = timezone.now()
        if reason:
            self.error_message = reason
        self.save(update_fields=["status", "finished_at", "error_message"])

    def update_counters(
        self,
        *,
        found: int = 0,
        processed: int = 0,
        new: int = 0,
        updated: int = 0,
    ) -> None:
        self.total_found = found or self.total_found
        self.total_processed += processed
        self.total_new += new
        self.total_updated += updated
        self.save(
            update_fields=["total_found", "total_processed", "total_new", "total_updated"]
        )


class GeoLocationProvider(models.TextChoices):
    NOMINATIM = "NOMINATIM", "OpenStreetMap Nominatim"


class GeoLocationCache(models.Model):
    provider = models.CharField(
        max_length=32,
        choices=GeoLocationProvider.choices,
        default=GeoLocationProvider.NOMINATIM,
        db_index=True,
    )
    query = models.CharField(max_length=255)
    normalized_query = models.CharField(max_length=255)
    country_code = models.CharField(max_length=2, blank=True, db_index=True)

    is_hit = models.BooleanField(default=False)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    display_name = models.CharField(max_length=512, blank=True)
    city = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)

    raw_payload = models.JSONField(default=dict)
    hits = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Geo Location Cache"
        verbose_name_plural = "Geo Location Cache"
        ordering = ["-last_used_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "normalized_query", "country_code"],
                name="uniq_geo_cache_provider_query_country",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "normalized_query", "country_code"]),
            models.Index(fields=["last_used_at"]),
        ]

    def __str__(self) -> str:
        suffix = f" [{self.country_code}]" if self.country_code else ""
        return f"{self.provider}: {self.query}{suffix}"
