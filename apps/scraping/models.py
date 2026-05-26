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
