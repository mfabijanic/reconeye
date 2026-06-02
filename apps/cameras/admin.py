from __future__ import annotations

import logging
from typing import Any

from django.contrib import admin, messages
from django.db.models import CharField, F, Q
from django.db.models.functions import Cast, Lower, Trim
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.common.cache import (
    invalidate_all,
    invalidate_cameras,
    invalidate_dashboard,
    invalidate_scrape_jobs,
)

from .models import Camera, CameraCheckLog, Go2RTCConfigSnapshot, Go2RTCInstance, Go2RTCStream, MapUISettings

logger = logging.getLogger(__name__)


class GeoFallbackCountryListFilter(admin.SimpleListFilter):
    title = _("Geo fallback (country)")
    parameter_name = "geo_fallback_country"

    def lookups(self, request, model_admin):
        return (("1", _("Yes")), ("0", _("No")))

    def queryset(self, request, queryset):
        value = self.value()
        if value not in {"1", "0"}:
            return queryset

        qs = queryset.annotate(
            geocode_query_norm=Lower(
                Trim(Cast(F("source_payload__geocoded__query"), output_field=CharField()))
            ),
            country_norm=Lower(Trim(F("country"))),
            country_code_norm=Lower(Trim(F("country_code"))),
        ).filter(
            Q(source_payload__geocoded__found=True)
            & Q(geocode_query_norm__isnull=False)
            & ~Q(geocode_query_norm="")
            & (
                Q(geocode_query_norm=F("country_norm"))
                | Q(geocode_query_norm=F("country_code_norm"))
            )
        )

        if value == "1":
            return qs
        return queryset.exclude(pk__in=qs.values("pk"))


# ── Cache invalidation actions ───────────────────────────────────────────────
@admin.action(description=_("Invalidate cameras cache"))
def invalidate_cameras_cache(modeladmin, request, queryset) -> None:
    invalidate_cameras()
    messages.success(request, _("Cameras cache invalidated."))


@admin.action(description=_("Invalidate dashboard cache"))
def invalidate_dashboard_cache(modeladmin, request, queryset) -> None:
    invalidate_dashboard()
    messages.success(request, _("Dashboard cache invalidated."))


@admin.action(description=_("Invalidate ALL cache"))
def invalidate_all_cache(modeladmin, request, queryset) -> None:
    invalidate_all()
    messages.success(request, _("All cache invalidated."))


@admin.action(description=_("Refresh Nominatim geocache for selected cameras"))
def refresh_selected_camera_geolocation(modeladmin, request, queryset) -> None:
    from apps.scraping.tasks import refresh_geolocation_for_cameras

    selected_ids = list(queryset.values_list("id", flat=True))
    if not selected_ids:
        messages.warning(request, _("No cameras selected."))
        return

    task = refresh_geolocation_for_cameras.delay(selected_ids)
    messages.success(
        request,
        _("Queued geolocation refresh for %(count)s camera(s). Task: %(task_id)s")
        % {"count": len(selected_ids), "task_id": task.id},
    )


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
    list_filter = (
        GeoFallbackCountryListFilter,
        "source_type",
        "is_online",
        "is_active",
        "has_partial_metadata",
        "country",
    )
    search_fields = ("title", "country", "city", "page_url", "stream_url")
    readonly_fields = ("created_at", "updated_at", "last_checked")
    list_per_page = 50
    actions = [
        invalidate_cameras_cache,
        invalidate_dashboard_cache,
        invalidate_all_cache,
        refresh_selected_camera_geolocation,
    ]

    fieldsets = (
        (None, {"fields": ("title", "source_type", "is_active")}),
        (_("Location"), {"fields": ("country", "city", "latitude", "longitude")}),
        (_("URLs"), {"fields": ("stream_url", "preview_image", "page_url")}),
        (_("Status"), {"fields": ("is_online", "has_partial_metadata", "last_checked")}),
        (_("Payload"), {"fields": ("source_payload",), "classes": ("collapse",)}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def stream_link(self, obj: Camera) -> str:
        if obj.stream_url:
            return format_html('<a href="{}" target="_blank">▶ {}</a>', obj.stream_url, _("stream"))
        return "—"

    stream_link.short_description = _("Stream")


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


@admin.register(Go2RTCInstance)
class Go2RTCInstanceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "scheme",
        "host",
        "port",
        "is_active",
        "last_sync_status",
        "last_synced_at",
    )
    list_filter = ("is_active", "last_sync_status", "scheme")
    search_fields = ("name", "host")
    readonly_fields = ("created_at", "updated_at", "last_synced_at")


@admin.register(Go2RTCStream)
class Go2RTCStreamAdmin(admin.ModelAdmin):
    list_display = (
        "instance",
        "stream_name",
        "producers_count",
        "consumers_count",
        "last_seen_at",
    )
    list_filter = ("instance",)
    search_fields = ("stream_name", "instance__name")
    readonly_fields = ("first_seen_at", "last_seen_at")


@admin.register(Go2RTCConfigSnapshot)
class Go2RTCConfigSnapshotAdmin(admin.ModelAdmin):
    list_display = ("instance", "fetched_at", "is_changed", "config_hash")
    list_filter = ("instance", "is_changed")
    search_fields = ("instance__name",)
    readonly_fields = ("instance", "config_payload", "config_hash", "is_changed", "change_summary", "fetched_at")

    def has_add_permission(self, request) -> bool:
        return False
