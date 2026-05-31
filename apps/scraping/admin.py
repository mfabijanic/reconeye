from __future__ import annotations

import logging
from typing import Any

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from apps.common.cache import invalidate_scrape_jobs
from apps.scraping.models import GeoLocationCache, ScrapeJob, ScrapeJobStatus

logger = logging.getLogger(__name__)


@admin.action(description=_("Invalidate scrape jobs cache"))
def invalidate_scrape_jobs_cache(modeladmin, request, queryset) -> None:
    invalidate_scrape_jobs()
    messages.success(request, _("Scrape jobs cache invalidated."))


@admin.action(description=_("Trigger Insecam scrape now"))
def trigger_insecam_scrape(modeladmin, request, queryset) -> None:
    from apps.scraping.tasks import scrape_insecam

    task = scrape_insecam.delay()
    messages.success(request, _("Insecam scrape task queued: %(task_id)s") % {"task_id": task.id})


@admin.action(description=_("Trigger WhatsUpCams scrape now"))
def trigger_whatsupcams_scrape(modeladmin, request, queryset) -> None:
    from apps.scraping.tasks import scrape_whatsupcams

    task = scrape_whatsupcams.delay()
    messages.success(request, _("WhatsUpCams scrape task queued: %(task_id)s") % {"task_id": task.id})


@admin.register(ScrapeJob)
class ScrapeJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source_type",
        "target_country_code",
        "status",
        "progress_pct_display",
        "total_found",
        "total_processed",
        "total_new",
        "total_updated",
        "started_at",
        "finished_at",
        "duration_display",
    )
    list_filter = ("source_type", "status")
    readonly_fields = (
        "source_type",
        "target_country_code",
        "status",
        "celery_task_id",
        "started_at",
        "finished_at",
        "total_found",
        "total_processed",
        "total_new",
        "total_updated",
        "error_message",
        "created_at",
    )
    search_fields = ("celery_task_id", "error_message")
    list_per_page = 50
    actions = [
        invalidate_scrape_jobs_cache,
        trigger_insecam_scrape,
        trigger_whatsupcams_scrape,
    ]

    def has_add_permission(self, request) -> bool:
        return False

    def progress_pct_display(self, obj: ScrapeJob) -> str:
        return f"{obj.progress_pct}%"

    progress_pct_display.short_description = _("Progress")

    def duration_display(self, obj: ScrapeJob) -> str:
        secs = obj.duration_seconds
        if secs is None:
            return "—"
        mins, s = divmod(int(secs), 60)
        return f"{mins}m {s}s" if mins else f"{s}s"

    duration_display.short_description = _("Duration")


@admin.register(GeoLocationCache)
class GeoLocationCacheAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "query",
        "country_code",
        "is_hit",
        "hits",
        "city",
        "region",
        "last_used_at",
    )
    list_filter = ("provider", "is_hit", "country_code")
    search_fields = ("query", "display_name", "city", "region")
    readonly_fields = (
        "provider",
        "query",
        "normalized_query",
        "country_code",
        "is_hit",
        "latitude",
        "longitude",
        "display_name",
        "city",
        "region",
        "zip_code",
        "raw_payload",
        "hits",
        "created_at",
        "updated_at",
        "last_used_at",
    )
    list_per_page = 100

    def has_add_permission(self, request) -> bool:
        return False
