from __future__ import annotations

import logging
from typing import Any

from django.contrib import admin, messages
from django.utils.html import format_html

from apps.common.cache import (
    invalidate_all,
    invalidate_cameras,
    invalidate_dashboard,
    invalidate_scrape_jobs,
)

from .models import Camera, CameraCheckLog, MapUISettings

logger = logging.getLogger(__name__)


# ── Cache invalidation actions ───────────────────────────────────────────────
@admin.action(description="Invalidate cameras cache")
def invalidate_cameras_cache(modeladmin, request, queryset) -> None:
    invalidate_cameras()
    messages.success(request, "Cameras cache invalidated.")


@admin.action(description="Invalidate dashboard cache")
def invalidate_dashboard_cache(modeladmin, request, queryset) -> None:
    invalidate_dashboard()
    messages.success(request, "Dashboard cache invalidated.")


@admin.action(description="Invalidate ALL cache")
def invalidate_all_cache(modeladmin, request, queryset) -> None:
    invalidate_all()
    messages.success(request, "All cache invalidated.")


# ── Camera admin ─────────────────────────────────────────────────────────────
@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "source_type",
        "country",
        "city",
        "is_online",
        "is_active",
        "has_partial_metadata",
        "last_checked",
        "created_at",
    )
    list_filter = ("source_type", "is_online", "is_active", "has_partial_metadata", "country")
    search_fields = ("title", "country", "city", "page_url", "stream_url")
    readonly_fields = ("created_at", "updated_at", "last_checked")
    list_per_page = 50
    actions = [invalidate_cameras_cache, invalidate_dashboard_cache, invalidate_all_cache]

    fieldsets = (
        (None, {"fields": ("title", "source_type", "is_active")}),
        ("Location", {"fields": ("country", "city", "latitude", "longitude")}),
        ("URLs", {"fields": ("stream_url", "preview_image", "page_url")}),
        ("Status", {"fields": ("is_online", "has_partial_metadata", "last_checked")}),
        ("Payload", {"fields": ("source_payload",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def stream_link(self, obj: Camera) -> str:
        if obj.stream_url:
            return format_html('<a href="{}" target="_blank">▶ stream</a>', obj.stream_url)
        return "—"

    stream_link.short_description = "Stream"


@admin.register(CameraCheckLog)
class CameraCheckLogAdmin(admin.ModelAdmin):
    list_display = ("camera", "checked_at", "is_online", "response_time_ms", "error_message")
    list_filter = ("is_online",)
    search_fields = ("camera__title",)
    readonly_fields = ("camera", "checked_at", "is_online", "response_time_ms", "error_message")
    list_per_page = 100

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(MapUISettings)
class MapUISettingsAdmin(admin.ModelAdmin):
    list_display = (
        "disable_clustering_at_zoom",
        "marker_limit",
        "status_stale_minutes",
        "popup_close_on_mouseout",
        "updated_at",
    )
    fields = (
        "disable_clustering_at_zoom",
        "marker_limit",
        "status_stale_minutes",
        "popup_close_on_mouseout",
        "updated_at",
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request) -> bool:
        return not MapUISettings.objects.exists()

    def has_delete_permission(self, request, obj: MapUISettings | None = None) -> bool:
        return False
