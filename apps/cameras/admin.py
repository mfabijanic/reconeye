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

from .models import (
    Camera,
    CameraCheckLog,
    Go2RTCConfigSnapshot,
    Go2RTCGridItem,
    Go2RTCGridProfile,
    Go2RTCInstance,
    Go2RTCStream,
    MapUISettings,
)

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


@admin.action(description=_("Re-resolve host IPs (for auto-grouping)"))
def reresolve_go2rtc_ips(modeladmin, request, queryset) -> None:
    from apps.cameras.services import resolve_host_ips
    from django.utils import timezone

    updated = 0
    failed = 0
    now = timezone.now()
    for instance in queryset:
        ips = resolve_host_ips(instance.host)
        if ips:
            instance.resolved_ips = ips
            instance.ips_resolved_at = now
            instance.save(update_fields=["resolved_ips", "ips_resolved_at", "updated_at"])
            updated += 1
        else:
            failed += 1
    messages.success(
        request,
        _("Re-resolved %(ok)s instance(s); %(failed)s could not be resolved.")
        % {"ok": updated, "failed": failed},
    )


@admin.action(description=_("Refresh GeoIP location"))
def refresh_go2rtc_geo(modeladmin, request, queryset) -> None:
    from apps.cameras.services import refresh_instance_geoip

    found = 0
    no_public_ip = 0
    geoip_miss = 0
    for instance in queryset:
        result = refresh_instance_geoip(instance)
        if result.get("found"):
            found += 1
        elif result.get("error") == "no_public_ips":
            no_public_ip += 1
        else:
            geoip_miss += 1

    messages.success(
        request,
        _(
            "GeoIP refresh completed: %(found)s located, %(no_public_ip)s without public IPs, %(geoip_miss)s public IPs without GeoIP match."
        )
        % {"found": found, "no_public_ip": no_public_ip, "geoip_miss": geoip_miss},
    )


@admin.action(description=_("Sync selected go2rtc instances"))
def sync_go2rtc_instances(modeladmin, request, queryset) -> None:
    from apps.cameras.tasks import sync_go2rtc_instance_task

    queued = 0
    for instance in queryset:
        sync_go2rtc_instance_task.delay(instance.pk)
        queued += 1

    messages.success(
        request,
        _("Queued sync for %(count)s go2rtc instance(s).")
        % {"count": queued},
    )


@admin.register(Go2RTCInstance)
class Go2RTCInstanceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "group_label",
        "is_private",
        "effective_location",
        "scheme",
        "host",
        "port",
        "path",
        "resolved_ips_display",
        "is_active",
        "last_sync_status",
        "last_synced_at",
        "created_at",
    )
    list_filter = (
        "is_active",
        "is_private",
        "last_sync_status",
        "scheme",
        "group_label",
        "location_override_enabled",
        "geo_country_code",
        "override_country_code",
    )
    search_fields = (
        "name",
        "host",
        "group_label",
        "geo_country",
        "geo_city",
        "override_country",
        "override_city",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "last_synced_at",
        "ips_resolved_at",
        "geo_resolved_at",
        "geo_ip_hash",
        "geo_provider",
        "geo_payload",
    )
    ordering = ("-created_at", "-id")
    actions = [reresolve_go2rtc_ips, refresh_go2rtc_geo, sync_go2rtc_instances]

    fieldsets = (
        (None, {
            "fields": (
                "name",
                "scheme",
                "host",
                "port",
                "path",
                "group_label",
                "is_active",
                "is_private",
            )
        }),
        (_("Auto GeoIP"), {
            "fields": (
                "geo_country",
                "geo_country_code",
                "geo_region",
                "geo_city",
                "geo_latitude",
                "geo_longitude",
                "geo_provider",
                "geo_resolved_at",
                "geo_ip_hash",
                "geo_payload",
            )
        }),
        (_("Manual override"), {
            "fields": (
                "location_override_enabled",
                "override_country",
                "override_country_code",
                "override_region",
                "override_city",
                "override_latitude",
                "override_longitude",
            )
        }),
        (_("Sync metadata"), {
            "fields": (
                "resolved_ips",
                "ips_resolved_at",
                "last_sync_status",
                "last_sync_error",
                "last_synced_at",
                "created_at",
                "updated_at",
            )
        }),
    )

    @admin.display(description=_("Resolved IPs"))
    def resolved_ips_display(self, obj: Go2RTCInstance) -> str:
        ips = obj.resolved_ips or []
        return ", ".join(str(ip) for ip in ips) if ips else "—"

    @admin.display(description=_("Location"))
    def effective_location(self, obj: Go2RTCInstance) -> str:
        city = obj.effective_city
        country = obj.effective_country
        code = obj.effective_country_code
        if city and country:
            return f"{city}, {country} ({code})" if code else f"{city}, {country}"
        if country:
            return f"{country} ({code})" if code else country
        return "—"


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


@admin.register(Go2RTCGridProfile)
class Go2RTCGridProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Go2RTCGridItem)
class Go2RTCGridItemAdmin(admin.ModelAdmin):
    list_display = ("profile", "instance", "stream_name", "title", "sort_order", "is_active")
    list_filter = ("profile", "instance", "is_active")
    search_fields = ("stream_name", "title", "profile__name", "instance__name")
    readonly_fields = ("created_at", "updated_at")
