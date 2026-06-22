from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import CharField, Count, F, Q
from django.db.models.functions import Cast, Lower, Trim
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.common.audit import log_audit_event
from apps.common.authz import CapabilityRequiredMixin, ROLE_OPERATOR, RoleRequiredMixin
from apps.cameras.forms import (
    Go2RTCBulkAddForm,
    Go2RTCCameraForm,
    Go2RTCGridProfileForm,
    Go2RTCImportForm,
    Go2RTCInstanceForm,
)
from apps.cameras.imports import CsvInstanceImportSource
from apps.cameras.models import (
    Camera,
    Go2RTCConfigSnapshot,
    Go2RTCGridItem,
    Go2RTCGridProfile,
    Go2RTCInstance,
    Go2RTCStream,
    MapUISettings,
    SourceType,
)
from apps.cameras.services import (
    build_config_diff_rows,
    build_go2rtc_stream_urls,
    build_camera_display_title,
    extract_camera_stream_id,
    find_go2rtc_group_page,
    fetch_go2rtc_streams,
    fetch_go2rtc_live_stream_counters,
    flatten_go2rtc_group_page,
    get_camera_map_markers,
    get_country_choices,
    get_go2rtc_country_choices,
    get_go2rtc_profile_tiles,
    import_go2rtc_instances,
    normalize_go2rtc_base_url,
    preview_go2rtc_import,
    sort_go2rtc_instance_groups,
    sync_go2rtc_instance,
    upsert_go2rtc_grid_item,
)
from apps.cameras.services_grid import (
    get_surveillance_grid_items_with_adapters,
    get_or_create_default_private_instance,
    get_surveillance_profile,
    remove_go2rtc_grid_item,
    upsert_go2rtc_grid_item as upsert_grid_item,
)
from apps.users.models import UserMapSettings


logger = logging.getLogger(__name__)

CAMERA_LIST_PAGE_SIZE = 25


def _to_bool_flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _apply_camera_list_filters(qs, request):
    if q := request.GET.get("q"):
        qs = qs.filter(title__icontains=q)
    if country := request.GET.get("country"):
        qs = qs.filter(country__iexact=country)
    if source := request.GET.get("source"):
        qs = qs.filter(source_type=source)
    if online := request.GET.get("online"):
        qs = qs.filter(is_online=online == "1")

    # Geolocation fallback filter:
    # show cameras where successful geocoding used a country-only query
    # (e.g., "Croatia", "Italy", "HR"), which usually means imprecise placement.
    if _to_bool_flag(request.GET.get("geo_fallback_country")):
        qs = qs.annotate(
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

    return qs


def _effective_map_settings_for_user(user) -> dict[str, int | bool]:
    base = MapUISettings.load()
    user_overrides = UserMapSettings.objects.filter(user=user).first()

    if not user_overrides:
        return {
            "disable_clustering_at_zoom": base.disable_clustering_at_zoom,
            "marker_limit": base.marker_limit,
            "status_stale_minutes": base.status_stale_minutes,
            "popup_close_on_mouseout": base.popup_close_on_mouseout,
        }

    return {
        "disable_clustering_at_zoom": (
            user_overrides.disable_clustering_at_zoom
            if user_overrides.disable_clustering_at_zoom is not None
            else base.disable_clustering_at_zoom
        ),
        "marker_limit": (
            user_overrides.marker_limit
            if user_overrides.marker_limit is not None
            else base.marker_limit
        ),
        "status_stale_minutes": (
            user_overrides.status_stale_minutes
            if user_overrides.status_stale_minutes is not None
            else base.status_stale_minutes
        ),
        "popup_close_on_mouseout": (
            user_overrides.popup_close_on_mouseout
            if user_overrides.popup_close_on_mouseout is not None
            else base.popup_close_on_mouseout
        ),
    }


class CameraListView(LoginRequiredMixin, ListView):
    model = Camera
    template_name = "cameras/list.html"
    context_object_name = "cameras"
    paginate_by = CAMERA_LIST_PAGE_SIZE

    def get_queryset(self):
        qs = Camera.objects.filter(is_active=True).order_by("-created_at")
        return _apply_camera_list_filters(qs, self.request)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["countries"] = get_country_choices()
        ctx["source_types"] = SourceType.choices
        ctx["q"] = self.request.GET.get("q", "")
        ctx["selected_country"] = self.request.GET.get("country", "")
        ctx["selected_source"] = self.request.GET.get("source", "")
        ctx["selected_online"] = self.request.GET.get("online", "")
        ctx["selected_geo_fallback_country"] = _to_bool_flag(
            self.request.GET.get("geo_fallback_country")
        )
        return ctx


class CameraDetailView(LoginRequiredMixin, DetailView):
    model = Camera
    template_name = "cameras/detail.html"
    context_object_name = "camera"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        camera = self.get_object()

        ctx["display_title"] = build_camera_display_title(
            source_type=camera.source_type,
            title=camera.title,
            city=camera.city,
            country=camera.country,
            camera_id=camera.pk,
        )
        ctx["stream_id"] = extract_camera_stream_id(
            source_type=camera.source_type,
            title=camera.title,
        )

        return ctx


class Go2RTCCameraGridView(LoginRequiredMixin, CapabilityRequiredMixin, TemplateView):
    template_name = "cameras/surveillance.html"
    required_capability = "surveillance"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        
        # Get surveillance grid items (private instances only)
        selected_cameras = get_surveillance_grid_items_with_adapters()
        
        # Get first private instance for form URL; don't block on stream discovery
        try:
            default_instance = get_or_create_default_private_instance()
            go2rtc_base_url = default_instance.base_url
        except Exception:
            go2rtc_base_url = ""
        
        # Stream discovery is deferred to HTMX endpoint to unblock initial render
        ctx["go2rtc_base_url"] = go2rtc_base_url
        ctx["go2rtc_streams"] = []  # Populated by HTMX partial endpoint
        ctx["go2rtc_source_error"] = None  # Populated by HTMX partial endpoint
        ctx["selected_cameras"] = selected_cameras
        ctx["go2rtc_form"] = Go2RTCCameraForm()
        return ctx


class AddGo2RTCCameraView(LoginRequiredMixin, CapabilityRequiredMixin, RoleRequiredMixin, View):
    required_capability = "surveillance"
    required_roles = (ROLE_OPERATOR,)

    def post(self, request, *args, **kwargs):
        form = Go2RTCCameraForm(request.POST)
        if not form.is_valid():
            error_html = '<div class="alert alert-danger alert-dismissible fade show" role="alert">'
            error_html += "Invalid input for the go2rtc camera."
            error_html += '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>'
            return HttpResponse(error_html)

        stream_name = form.cleaned_data["stream_name"].strip()
        title = form.cleaned_data["title"].strip()
        
        # Get or create default private instance
        instance = get_or_create_default_private_instance()
        profile = get_surveillance_profile()
        
        # Create/update grid item instead of Camera record
        grid_item, created = upsert_grid_item(
            instance=instance,
            stream_name=stream_name,
            title=title,
            profile=profile,
        )
        
        if created:
            message = f"Added to surveillance: {grid_item.title}"
            alert_class = "alert-success"
        else:
            message = f"Updated surveillance item: {grid_item.title}"
            alert_class = "alert-info"

        log_audit_event(
            request=request,
            action="create" if created else "update",
            target=grid_item,
            after_state={
                "profile_id": grid_item.profile_id,
                "instance_id": grid_item.instance_id,
                "stream_name": grid_item.stream_name,
                "title": grid_item.title,
                "is_active": grid_item.is_active,
            },
            metadata={"operation": "surveillance_upsert"},
        )
        
        success_html = f'<div class="alert {alert_class} alert-dismissible fade show" role="alert">'
        success_html += message
        success_html += '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>'
        return HttpResponse(success_html)


class RemoveGo2RTCCameraView(LoginRequiredMixin, CapabilityRequiredMixin, RoleRequiredMixin, View):
    required_capability = "surveillance"
    required_roles = (ROLE_OPERATOR,)

    def post(self, request, pk: int, *args, **kwargs):
        # pk is now Go2RTCGridItem.pk (not Camera.pk)
        grid_item = get_object_or_404(Go2RTCGridItem, pk=pk)
        before_state = {
            "profile_id": grid_item.profile_id,
            "instance_id": grid_item.instance_id,
            "stream_name": grid_item.stream_name,
            "title": grid_item.title,
            "is_active": grid_item.is_active,
        }
        remove_go2rtc_grid_item(grid_item)
        log_audit_event(
            request=request,
            action="delete",
            target=grid_item,
            before_state=before_state,
            after_state={**before_state, "is_active": False},
            metadata={"operation": "surveillance_remove"},
        )
        messages.success(request, f"Removed from surveillance: {grid_item.title or grid_item.stream_name}")
        return redirect("cameras:surveillance")


class Go2RTCManagerView(LoginRequiredMixin, CapabilityRequiredMixin, TemplateView):
    template_name = "cameras/go2rtc_manager.html"
    required_capability = "go2rtc_manager"

    PAGE_SIZE_CHOICES = (5, 10, 25, 50, 100)
    DEFAULT_PAGE_SIZE = 5
    STREAM_PAGE_SIZE_CHOICES = (5, 25, 50, 100)
    DEFAULT_STREAM_PAGE_SIZE = 25
    # Above this serialized size (bytes) we skip the raw config dump in the UI
    # to avoid rendering multi-megabyte payloads (e.g. instances with tens of
    # thousands of streams).
    MAX_CONFIG_RENDER_BYTES = 256 * 1024

    # Maps the ?sort= query value to an order_by expression. The stream-count
    # options use the annotated `stream_count` field.
    SORT_OPTIONS = {
        "newest": ("-created_at", "-id"),
        "group": ("group_label", "name"),
        "name": ("name",),
        "name_desc": ("-name",),
        "streams_desc": ("-stream_count", "name"),
        "streams_asc": ("stream_count", "name"),
        "status": ("last_sync_status", "name"),
    }
    DEFAULT_SORT = "newest"

    def _resolve_page_size(self) -> int:
        raw = self.request.GET.get("per_page")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return self.DEFAULT_PAGE_SIZE
        return value if value in self.PAGE_SIZE_CHOICES else self.DEFAULT_PAGE_SIZE

    def _resolve_sort(self) -> str:
        sort = self.request.GET.get("sort")
        return sort if sort in self.SORT_OPTIONS else self.DEFAULT_SORT

    def _resolve_stream_page_size(self) -> int:
        raw = self.request.GET.get("stream_per_page")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return self.DEFAULT_STREAM_PAGE_SIZE
        return (
            value
            if value in self.STREAM_PAGE_SIZE_CHOICES
            else self.DEFAULT_STREAM_PAGE_SIZE
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sort_key = self._resolve_sort()
        all_instances = Go2RTCInstance.objects.filter(is_active=True, is_private=False).annotate(
            stream_count=Count("streams")
        )

        # Free-text search across instance name, host, base URL and group label.
        # Activated either by clicking the search field or via keyboard
        # shortcut handled on the client (see template).
        search_query = (self.request.GET.get("q") or "").strip()
        instances = all_instances
        if search_query:
            instances = instances.filter(
                Q(name__icontains=search_query)
                | Q(host__icontains=search_query)
                | Q(group_label__icontains=search_query)
            )

        country_filter = (self.request.GET.get("country") or "").strip()
        city_filter = (self.request.GET.get("city") or "").strip()
        has_geo_filter = (self.request.GET.get("has_geo") or "").strip().lower()

        if country_filter:
            instances = instances.filter(
                Q(location_override_enabled=True, override_country__iexact=country_filter)
                | Q(location_override_enabled=False, geo_country__iexact=country_filter)
                | Q(
                    location_override_enabled=True,
                    override_country="",
                    geo_country__iexact=country_filter,
                )
            )

        if city_filter:
            instances = instances.filter(
                Q(location_override_enabled=True, override_city__icontains=city_filter)
                | Q(location_override_enabled=False, geo_city__icontains=city_filter)
                | Q(location_override_enabled=True, override_city="", geo_city__icontains=city_filter)
            )

        if has_geo_filter in {"1", "true", "yes", "on"}:
            instances = instances.filter(
                Q(location_override_enabled=True, override_latitude__isnull=False, override_longitude__isnull=False)
                | Q(location_override_enabled=False, geo_latitude__isnull=False, geo_longitude__isnull=False)
                | Q(
                    location_override_enabled=True,
                    override_latitude__isnull=True,
                    override_longitude__isnull=True,
                    geo_latitude__isnull=False,
                    geo_longitude__isnull=False,
                )
            )

        # Sort and paginate the grouped instance list so the sidebar is driven
        # by logical groups first, then instances within each group.
        page_size = self._resolve_page_size()
        selected_id = self.request.GET.get("instance")
        try:
            selected_instance_id = int(selected_id) if selected_id else None
        except (TypeError, ValueError):
            selected_instance_id = None

        grouped_instances_all = sort_go2rtc_instance_groups(
            list(instances),
            sort_key=sort_key,
        )
        paginator = Paginator(grouped_instances_all, page_size)
        page_number = self.request.GET.get("page")
        if not page_number and selected_instance_id is not None:
            page_number = str(
                find_go2rtc_group_page(
                    grouped_instances_all,
                    selected_instance_id=selected_instance_id,
                    page_size=page_size,
                )
            )
        try:
            instances_page = paginator.page(page_number)
        except PageNotAnInteger:
            instances_page = paginator.page(1)
        except EmptyPage:
            instances_page = paginator.page(paginator.num_pages)

        grouped_instances_list = list(instances_page.object_list)
        current_page_instances = flatten_go2rtc_group_page(grouped_instances_list)
        group_view = True

        # Resolve the selected instance against the full (unpaginated) set so a
        # deep-linked ?instance=<pk> still works regardless of the active page.
        selected_instance = None
        if selected_instance_id is not None:
            selected_instance = all_instances.filter(pk=selected_instance_id).first()
        if selected_instance is None:
            selected_instance = current_page_instances[0] if current_page_instances else None

        streams_qs = Go2RTCStream.objects.none()
        latest_config = None
        config_history = Go2RTCConfigSnapshot.objects.none()
        compare_from = None
        compare_to = None
        diff_rows: list[dict[str, str]] = []
        stream_choices: list[tuple[str, str]] = []
        profiles = Go2RTCGridProfile.objects.filter(is_active=True).order_by("name")
        selected_profile = None
        selected_profile_id = self.request.GET.get("profile")
        if selected_profile_id:
            try:
                selected_profile = profiles.filter(pk=int(selected_profile_id)).first()
            except (TypeError, ValueError):
                selected_profile = None
        if selected_profile is None:
            selected_profile = profiles.first()
        streams_page = None
        stream_query = (self.request.GET.get("stream_q") or "").strip()
        stream_page_size = self._resolve_stream_page_size()
        stream_total = 0
        stream_filtered_total = 0
        if selected_instance is not None:
            streams_qs = selected_instance.streams.order_by("stream_name")
            stream_total = streams_qs.count()
            if stream_query:
                streams_qs = streams_qs.filter(stream_name__icontains=stream_query)

            # Paginate streams so instances with thousands of streams stay
            # responsive (and the bulk-add table doesn't render everything).
            stream_paginator = Paginator(streams_qs, stream_page_size)
            stream_filtered_total = stream_paginator.count
            try:
                streams_page = stream_paginator.page(self.request.GET.get("stream_page"))
            except PageNotAnInteger:
                streams_page = stream_paginator.page(1)
            except EmptyPage:
                streams_page = stream_paginator.page(stream_paginator.num_pages)

            # Bulk-add checkboxes only cover the streams visible on this page,
            # so a single huge instance never produces a megabyte-scale form.
            stream_choices = [(s.stream_name, s.stream_name) for s in streams_page.object_list]

            latest_config = selected_instance.config_snapshots.order_by("-fetched_at").first()
            config_history = selected_instance.config_snapshots.order_by("-fetched_at", "-id")[:50]

            if latest_config is not None:
                try:
                    import json as _json

                    latest_config_size = len(
                        _json.dumps(latest_config.config_payload or {})
                    )
                except (TypeError, ValueError):
                    latest_config_size = 0
                ctx["latest_config_size"] = latest_config_size
                ctx["latest_config_too_large"] = (
                    latest_config_size > self.MAX_CONFIG_RENDER_BYTES
                )

            snapshots = list(config_history)
            from_id_raw = self.request.GET.get("diff_from")
            to_id_raw = self.request.GET.get("diff_to")

            try:
                from_id = int(from_id_raw) if from_id_raw else None
            except (TypeError, ValueError):
                from_id = None
            try:
                to_id = int(to_id_raw) if to_id_raw else None
            except (TypeError, ValueError):
                to_id = None

            if snapshots:
                by_id = {row.id: row for row in snapshots}
                if len(snapshots) >= 2:
                    compare_to = by_id.get(to_id) if to_id else snapshots[0]
                    compare_from = by_id.get(from_id) if from_id else snapshots[1]
                    if compare_from and compare_to and compare_from.id != compare_to.id:
                        diff_rows = build_config_diff_rows(
                            compare_from.config_payload or {},
                            compare_to.config_payload or {},
                        )
                elif len(snapshots) == 1:
                    compare_to = snapshots[0]

        ctx["instances"] = current_page_instances
        ctx["instances_page"] = instances_page
        ctx["grouped_instances"] = grouped_instances_list
        ctx["group_view"] = group_view
        ctx["instance_total"] = all_instances.count()
        ctx["instance_filtered_total"] = len(grouped_instances_all and flatten_go2rtc_group_page(grouped_instances_all) or [])
        ctx["instance_group_total"] = len(grouped_instances_all)
        ctx["search_query"] = search_query
        ctx["country_choices"] = get_go2rtc_country_choices()
        ctx["selected_country"] = country_filter
        ctx["selected_city"] = city_filter
        ctx["selected_has_geo"] = has_geo_filter in {"1", "true", "yes", "on"}
        ctx["page_size"] = page_size
        ctx["page_size_choices"] = self.PAGE_SIZE_CHOICES
        ctx["sort"] = sort_key
        ctx["profiles"] = profiles
        ctx["selected_profile"] = selected_profile
        ctx["selected_instance"] = selected_instance
        ctx["streams"] = streams_page.object_list if streams_page else []
        ctx["streams_page"] = streams_page
        ctx["stream_query"] = stream_query
        ctx["stream_page_size"] = stream_page_size
        ctx["stream_page_size_choices"] = self.STREAM_PAGE_SIZE_CHOICES
        ctx["stream_total"] = stream_total
        ctx["stream_filtered_total"] = stream_filtered_total
        ctx["latest_config"] = latest_config
        ctx.setdefault("latest_config_size", 0)
        ctx.setdefault("latest_config_too_large", False)
        ctx["config_history"] = config_history
        ctx["compare_from"] = compare_from
        ctx["compare_to"] = compare_to
        ctx["diff_rows"] = diff_rows
        ctx["instance_form"] = kwargs.get("instance_form") or Go2RTCInstanceForm()
        profile_choices = [(str(p.pk), p.name) for p in profiles]
        ctx["profile_form"] = kwargs.get("profile_form") or Go2RTCGridProfileForm()
        ctx["bulk_form"] = kwargs.get("bulk_form") or Go2RTCBulkAddForm(
            stream_choices=stream_choices,
            profile_choices=profile_choices,
            initial={"profile_id": str(selected_profile.pk)} if selected_profile else None,
        )

        # Tab state: persisted via the ?tab= query parameter so the chosen tab
        # stays active across navigation/redirects until explicitly switched.
        tab = (self.request.GET.get("tab") or "").strip().lower()
        ctx["active_tab"] = tab if tab in {"instances", "setup", "import"} else "instances"
        ctx["import_form"] = kwargs.get("import_form") or Go2RTCImportForm()

        # Preserve manager list state when jumping to the viewer so users can
        # return to the same page/filters/selection afterwards.
        manager_return_params: dict[str, str] = {
            "manager_page": str(instances_page.number),
            "manager_sort": sort_key,
            "manager_per_page": str(page_size),
            "manager_stream_per_page": str(stream_page_size),
        }
        if ctx["active_tab"] != "instances":
            manager_return_params["tab"] = ctx["active_tab"]
        if search_query:
            manager_return_params["manager_q"] = search_query
        if country_filter:
            manager_return_params["manager_country"] = country_filter
        if city_filter:
            manager_return_params["manager_city"] = city_filter
        if has_geo_filter in {"1", "true", "yes", "on"}:
            manager_return_params["manager_has_geo"] = "1"
        if selected_profile is not None:
            manager_return_params["manager_profile"] = str(selected_profile.pk)

        ctx["manager_return_query"] = urlencode(manager_return_params)
        return ctx


class Go2RTCInstanceViewerView(LoginRequiredMixin, CapabilityRequiredMixin, TemplateView):
    required_capability = "go2rtc_manager"
    template_name = "cameras/go2rtc_viewer.html"

    VIEWER_SIZE_CHOICES = (4, 6)
    DEFAULT_VIEWER_SIZE = 4
    INSTANCE_PAGE_SIZE_CHOICES = (25, 50, 100, 200)
    DEFAULT_INSTANCE_PAGE_SIZE = 50
    SIDEBAR_MODES = {"pinned", "auto"}
    DEFAULT_SIDEBAR_MODE = "pinned"
    SORT_OPTIONS = {
        "newest": "newest",
        "group": "group",
        "name": "name",
        "name_desc": "name_desc",
        "streams_desc": "streams_desc",
        "streams_asc": "streams_asc",
        "status": "status",
    }
    DEFAULT_SORT = "newest"

    def _resolve_viewer_size(self) -> int:
        raw = self.request.GET.get("viewer_size")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return self.DEFAULT_VIEWER_SIZE
        return value if value in self.VIEWER_SIZE_CHOICES else self.DEFAULT_VIEWER_SIZE

    def _resolve_sidebar_mode(self) -> str:
        value = (self.request.GET.get("sidebar") or "").strip().lower()
        return value if value in self.SIDEBAR_MODES else self.DEFAULT_SIDEBAR_MODE

    def _resolve_instance_page_size(self) -> int:
        raw = self.request.GET.get("instance_per_page")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return self.DEFAULT_INSTANCE_PAGE_SIZE
        return (
            value
            if value in self.INSTANCE_PAGE_SIZE_CHOICES
            else self.DEFAULT_INSTANCE_PAGE_SIZE
        )

    def _resolve_sort(self) -> str:
        sort = (self.request.GET.get("sort") or "").strip().lower()
        return sort if sort in self.SORT_OPTIONS else self.DEFAULT_SORT

    def _apply_geo_filters(self, qs):
        country_filter = (self.request.GET.get("country") or "").strip()
        city_filter = (self.request.GET.get("city") or "").strip()
        has_geo_selected = _to_bool_flag(self.request.GET.get("has_geo"))

        if country_filter:
            qs = qs.filter(
                Q(location_override_enabled=True, override_country__iexact=country_filter)
                | Q(location_override_enabled=False, geo_country__iexact=country_filter)
                | Q(
                    location_override_enabled=True,
                    override_country="",
                    geo_country__iexact=country_filter,
                )
            )

        if city_filter:
            qs = qs.filter(
                Q(location_override_enabled=True, override_city__icontains=city_filter)
                | Q(location_override_enabled=False, geo_city__icontains=city_filter)
                | Q(
                    location_override_enabled=True,
                    override_city="",
                    geo_city__icontains=city_filter,
                )
            )

        if has_geo_selected:
            qs = qs.filter(
                Q(
                    location_override_enabled=True,
                    override_latitude__isnull=False,
                    override_longitude__isnull=False,
                )
                | Q(
                    location_override_enabled=False,
                    geo_latitude__isnull=False,
                    geo_longitude__isnull=False,
                )
                | Q(
                    location_override_enabled=True,
                    override_latitude__isnull=True,
                    override_longitude__isnull=True,
                    geo_latitude__isnull=False,
                    geo_longitude__isnull=False,
                )
            )

        return qs, country_filter, city_filter, has_geo_selected

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        instance_query = (self.request.GET.get("q") or "").strip()
        viewer_size = self._resolve_viewer_size()
        sidebar_mode = self._resolve_sidebar_mode()
        instance_page_size = self._resolve_instance_page_size()
        sort_key = self._resolve_sort()

        all_instances_qs = Go2RTCInstance.objects.filter(is_active=True, is_private=False).annotate(
            stream_count=Count("streams")
        )
        instance_total = all_instances_qs.count()

        filtered_instances_qs = all_instances_qs
        if instance_query:
            filtered_instances_qs = filtered_instances_qs.filter(
                Q(name__icontains=instance_query)
                | Q(host__icontains=instance_query)
                | Q(group_label__icontains=instance_query)
            )
        (
            filtered_instances_qs,
            country_filter,
            city_filter,
            has_geo_selected,
        ) = self._apply_geo_filters(filtered_instances_qs)

        selected_instance = None
        selected_id_raw = self.request.GET.get("instance")
        if selected_id_raw:
            try:
                selected_id = int(selected_id_raw)
            except (TypeError, ValueError):
                selected_id = None
            if selected_id is not None:
                selected_instance = all_instances_qs.filter(pk=selected_id).first()

        grouped_instances_all = sort_go2rtc_instance_groups(
            list(filtered_instances_qs),
            sort_key=sort_key,
        )
        instance_paginator = Paginator(grouped_instances_all, instance_page_size)
        resolved_instance_page = self.request.GET.get("instance_page")

        # Keep deep links stable: if an instance is selected and the client did
        # not force a sidebar page, automatically open the page containing it.
        if not resolved_instance_page and selected_instance is not None:
            selected_in_filtered = filtered_instances_qs.filter(pk=selected_instance.pk).exists()
            if selected_in_filtered:
                resolved_instance_page = str(
                    find_go2rtc_group_page(
                        grouped_instances_all,
                        selected_instance_id=selected_instance.pk,
                        page_size=instance_page_size,
                    )
                )

        try:
            instance_page = instance_paginator.page(resolved_instance_page)
        except PageNotAnInteger:
            instance_page = instance_paginator.page(1)
        except EmptyPage:
            instance_page = instance_paginator.page(instance_paginator.num_pages)

        grouped_instances = list(instance_page.object_list)
        instances = flatten_go2rtc_group_page(grouped_instances)
        group_view = True

        if selected_instance is None and instances:
            selected_instance = instances[0]

        # Carry manager-origin state through viewer navigation using prefixed
        # params so viewer filters don't overwrite manager filters.
        manager_state_keys = (
            "manager_instance",
            "manager_page",
            "manager_sort",
            "manager_per_page",
            "manager_stream_per_page",
            "manager_q",
            "manager_country",
            "manager_city",
            "manager_has_geo",
            "manager_profile",
        )
        manager_state_params: dict[str, str] = {}
        for key in manager_state_keys:
            value = (self.request.GET.get(key) or "").strip()
            if value:
                manager_state_params[key] = value

        viewer_page = None
        viewer_tiles: list[dict[str, object]] = []
        viewer_total = 0
        viewer_visible_count = 0
        viewer_page_start = 0
        viewer_page_end = 0
        active_tile = None

        if selected_instance is not None:
            viewer_stream_query = (self.request.GET.get("stream_q") or "").strip()
            viewer_streams_qs = selected_instance.streams.exclude(
                stream_name__iexact="xdebug"
            ).order_by("stream_name")
            if viewer_stream_query:
                viewer_streams_qs = viewer_streams_qs.filter(
                    stream_name__icontains=viewer_stream_query
                )

            viewer_total = viewer_streams_qs.count()
            viewer_paginator = Paginator(viewer_streams_qs, viewer_size)
            try:
                viewer_page = viewer_paginator.page(self.request.GET.get("viewer_page"))
            except PageNotAnInteger:
                viewer_page = viewer_paginator.page(1)
            except EmptyPage:
                viewer_page = viewer_paginator.page(viewer_paginator.num_pages)

            base_url = normalize_go2rtc_base_url(selected_instance.base_url)
            viewer_visible_count = len(viewer_page.object_list)
            viewer_page_start = ((viewer_page.number - 1) * viewer_size) + 1
            viewer_page_end = min(viewer_total, viewer_page_start + viewer_visible_count - 1)
            for index, stream in enumerate(viewer_page.object_list, start=1):
                urls = build_go2rtc_stream_urls(base_url, stream.stream_name)
                viewer_tiles.append(
                    {
                        "stream_name": stream.stream_name,
                        "title": stream.stream_name,
                        "producers_count": stream.producers_count,
                        "consumers_count": stream.consumers_count,
                        "viewer_url": urls["viewer"],
                        "webrtc_embed_url": urls["webrtc_embed"],
                        "focus_index": index,
                        "visible_total": viewer_visible_count,
                    }
                )
            active_tile = viewer_tiles[0] if viewer_tiles else None

        ctx["instances"] = instances
        ctx["instance_page"] = instance_page
        ctx["instance_page_size"] = instance_page_size
        ctx["instance_page_size_choices"] = self.INSTANCE_PAGE_SIZE_CHOICES
        ctx["grouped_instances"] = grouped_instances
        ctx["group_view"] = group_view
        ctx["selected_instance"] = selected_instance
        ctx["instance_query"] = instance_query
        ctx["sort"] = sort_key
        ctx["country_choices"] = get_go2rtc_country_choices()
        ctx["selected_country"] = country_filter
        ctx["selected_city"] = city_filter
        ctx["selected_has_geo"] = has_geo_selected
        ctx["instance_total"] = instance_total
        ctx["instance_filtered_total"] = instance_paginator.count
        ctx["viewer_size"] = viewer_size
        ctx["viewer_size_choices"] = self.VIEWER_SIZE_CHOICES
        ctx["sidebar_mode"] = sidebar_mode
        ctx["viewer_page"] = viewer_page
        ctx["viewer_tiles"] = viewer_tiles
        ctx["viewer_total"] = viewer_total
        ctx["viewer_visible_count"] = viewer_visible_count
        ctx["viewer_page_start"] = viewer_page_start
        ctx["viewer_page_end"] = viewer_page_end
        ctx["active_tile"] = active_tile
        ctx["viewer_live_metrics_url"] = (
            reverse("cameras:go2rtc_viewer_live_metrics", kwargs={"pk": selected_instance.pk})
            if selected_instance is not None
            else ""
        )

        manager_back_params: dict[str, str] = {}
        manager_to_back_key = {
            "manager_instance": "instance",
            "manager_page": "page",
            "manager_sort": "sort",
            "manager_per_page": "per_page",
            "manager_stream_per_page": "stream_per_page",
            "manager_q": "q",
            "manager_country": "country",
            "manager_city": "city",
            "manager_has_geo": "has_geo",
            "manager_profile": "profile",
        }
        for manager_key, back_key in manager_to_back_key.items():
            value = manager_state_params.get(manager_key)
            if value:
                manager_back_params[back_key] = value
        if "instance" not in manager_back_params and selected_instance is not None:
            manager_back_params["instance"] = str(selected_instance.pk)

        ctx["manager_state_query"] = urlencode(manager_state_params)
        ctx["manager_state_items"] = list(manager_state_params.items())
        ctx["manager_back_query"] = urlencode(manager_back_params)
        return ctx


class Go2RTCViewerLiveMetricsView(LoginRequiredMixin, CapabilityRequiredMixin, View):
    """Read-only endpoint with live producers/consumers for viewer tiles."""
    required_capability = "go2rtc_manager"

    def get(self, request, pk: int, *args, **kwargs):
        instance = get_object_or_404(Go2RTCInstance, pk=pk, is_active=True)
        counters, error = fetch_go2rtc_live_stream_counters(base_url=instance.base_url)
        payload = {
            "ok": error is None,
            "instance_id": instance.pk,
            "counters": counters,
        }
        if error:
            payload["error"] = error
        return JsonResponse(payload)


class AddGo2RTCInstanceView(LoginRequiredMixin, CapabilityRequiredMixin, RoleRequiredMixin, View):
    required_capability = "go2rtc_manager"
    required_roles = (ROLE_OPERATOR,)

    def post(self, request, *args, **kwargs):
        form = Go2RTCInstanceForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid go2rtc instance input.")
            return redirect(f"{reverse('cameras:go2rtc_manager')}?tab=setup")

        clean = form.cleaned_data
        existing_instance = Go2RTCInstance.objects.filter(name=clean["name"].strip()).first()
        before_state = None
        if existing_instance is not None:
            before_state = {
                "scheme": existing_instance.scheme,
                "host": existing_instance.host,
                "port": existing_instance.port,
                "path": existing_instance.path,
                "group_label": existing_instance.group_label,
                "is_active": existing_instance.is_active,
            }

        instance, created = Go2RTCInstance.objects.update_or_create(
            name=clean["name"].strip(),
            defaults={
                "scheme": clean["scheme"],
                "host": clean["host"].strip(),
                "port": int(clean["port"]),
                "path": (clean.get("path") or "").strip().strip("/"),
                "group_label": (clean.get("group_label") or "").strip(),
                "is_active": True,
            },
        )

        stream_count, error, warning = sync_go2rtc_instance(instance)
        if error:
            messages.warning(request, f"Instance saved, but sync failed: {error}")
        elif instance.last_sync_status == Go2RTCInstance.LastSyncStatus.UNAUTHORIZED:
            messages.warning(request, f"go2rtc instance {'added' if created else 'updated'}. Unauthorized: {warning or 'authentication required.'}")
        else:
            action = "added" if created else "updated"
            if warning:
                messages.warning(request, f"go2rtc instance {action}. Synced {stream_count} streams, but warning: {warning}")
            else:
                messages.success(request, f"go2rtc instance {action}. Synced {stream_count} streams.")
        log_audit_event(
            request=request,
            action="create" if created else "update",
            target=instance,
            before_state=before_state,
            after_state={
                "scheme": instance.scheme,
                "host": instance.host,
                "port": instance.port,
                "path": instance.path,
                "group_label": instance.group_label,
                "is_active": instance.is_active,
                "last_sync_status": instance.last_sync_status,
            },
            metadata={"operation": "go2rtc_instance_upsert", "stream_count": stream_count, "warning": warning or "", "error": error or ""},
        )
        return redirect(
            f"{reverse('cameras:go2rtc_manager')}?tab=setup&instance={instance.pk}"
        )


class SyncGo2RTCInstanceView(LoginRequiredMixin, CapabilityRequiredMixin, RoleRequiredMixin, View):
    required_capability = "go2rtc_manager"
    required_roles = (ROLE_OPERATOR,)

    def post(self, request, pk: int, *args, **kwargs):
        instance = get_object_or_404(Go2RTCInstance, pk=pk, is_active=True)
        before_state = {
            "last_sync_status": instance.last_sync_status,
            "last_sync_error": instance.last_sync_error,
            "last_synced_at": instance.last_synced_at.isoformat() if instance.last_synced_at else None,
        }
        stream_count, error, warning = sync_go2rtc_instance(instance)
        if error:
            messages.error(request, f"Sync failed for {instance.name}: {error}")
        elif instance.last_sync_status == Go2RTCInstance.LastSyncStatus.UNAUTHORIZED:
            messages.warning(request, f"Sync unauthorized for {instance.name}: {warning or 'authentication required.'}")
        else:
            if warning:
                messages.warning(request, f"Sync completed for {instance.name}. {stream_count} streams available. Warning: {warning}")
            else:
                messages.success(request, f"Sync completed for {instance.name}. {stream_count} streams available.")

        # Preserve current manager UI state after sync (search/filter/pagination).
        manager_state_keys = (
            "q",
            "sort",
            "per_page",
            "stream_per_page",
            "page",
            "country",
            "city",
            "has_geo",
            "profile",
            "stream_q",
            "stream_page",
            "diff_from",
            "diff_to",
            "tab",
        )
        redirect_params: dict[str, str] = {
            "instance": str(instance.pk),
        }
        for key in manager_state_keys:
            value = (request.POST.get(key) or "").strip()
            if value:
                redirect_params[key] = value

        manager_url = reverse("cameras:go2rtc_manager")
        log_audit_event(
            request=request,
            action="execute",
            target=instance,
            before_state=before_state,
            after_state={
                "last_sync_status": instance.last_sync_status,
                "last_sync_error": instance.last_sync_error,
                "last_synced_at": instance.last_synced_at.isoformat() if instance.last_synced_at else None,
            },
            metadata={"operation": "go2rtc_sync", "stream_count": stream_count, "warning": warning or "", "error": error or ""},
        )
        return redirect(f"{manager_url}?{urlencode(redirect_params)}")


class Go2RTCImportPreviewView(LoginRequiredMixin, CapabilityRequiredMixin, RoleRequiredMixin, View):
    required_capability = "go2rtc_manager"
    required_roles = (ROLE_OPERATOR,)

    """Dry-run: parse the submitted CSV and render a preview table.

    Writes nothing. The exact payload is re-serialized (base64) into the
    rendered confirm form so the commit step re-parses the same content
    without any server-side temp state.
    """

    def post(self, request, *args, **kwargs):
        import base64

        form = Go2RTCImportForm(request.POST, request.FILES)
        if not form.is_valid():
            error = " ".join(
                msg for errors in form.errors.values() for msg in errors
            ) or "Provide a CSV file or paste CSV text."
            html = render_to_string(
                "htmx/cameras/_import_preview.html",
                {"form_error": error},
                request=request,
            )
            return HttpResponse(html)

        raw = form.get_content()
        rows = preview_go2rtc_import(CsvInstanceImportSource(raw))
        valid_count = sum(1 for r in rows if r.is_valid)
        invalid_count = len(rows) - valid_count

        if isinstance(raw, str):
            raw_bytes = raw.encode("utf-8")
        else:
            raw_bytes = raw
        csv_b64 = base64.b64encode(raw_bytes).decode("ascii")

        html = render_to_string(
            "htmx/cameras/_import_preview.html",
            {
                "rows": rows,
                "valid_count": valid_count,
                "invalid_count": invalid_count,
                "csv_b64": csv_b64,
            },
            request=request,
        )
        return HttpResponse(html)


class Go2RTCImportConfirmView(LoginRequiredMixin, CapabilityRequiredMixin, RoleRequiredMixin, View):
    required_capability = "go2rtc_manager"
    required_roles = (ROLE_OPERATOR,)

    """Commit: upsert instances from the previewed CSV and dispatch async sync."""

    def post(self, request, *args, **kwargs):
        import base64
        import binascii

        import_url = f"{reverse('cameras:go2rtc_manager')}?tab=import"
        csv_b64 = request.POST.get("csv_b64", "")
        if not csv_b64:
            messages.error(request, "Nothing to import.")
            return redirect(import_url)

        try:
            csv_bytes = base64.b64decode(csv_b64.encode("ascii"), validate=True)
        except (binascii.Error, ValueError):
            messages.error(request, "Import payload was corrupted; please preview again.")
            return redirect(import_url)

        report = import_go2rtc_instances(CsvInstanceImportSource(csv_bytes), sync=True)
        log_audit_event(
            request=request,
            action="execute",
            target_label="go2rtc import",
            after_state={
                "created": report.created,
                "updated": report.updated,
                "skipped": report.skipped,
                "synced_dispatched": report.synced_dispatched,
            },
            metadata={"operation": "go2rtc_import_confirm"},
        )
        messages.success(
            request,
            (
                f"Import done: {report.created} added, {report.updated} updated, "
                f"{report.skipped} skipped. Sync dispatched for "
                f"{report.synced_dispatched} instance(s)."
            ),
        )
        return redirect(import_url)


class BulkAddGo2RTCStreamsView(LoginRequiredMixin, CapabilityRequiredMixin, RoleRequiredMixin, View):
    required_capability = "go2rtc_manager"
    required_roles = (ROLE_OPERATOR,)

    def post(self, request, pk: int, *args, **kwargs):
        instance = get_object_or_404(Go2RTCInstance, pk=pk, is_active=True)
        streams_qs = instance.streams.order_by("stream_name")
        stream_choices = [(s.stream_name, s.stream_name) for s in streams_qs]
        profile_choices = [
            (str(profile.pk), profile.name)
            for profile in Go2RTCGridProfile.objects.filter(is_active=True).order_by("name")
        ]
        form = Go2RTCBulkAddForm(
            request.POST,
            stream_choices=stream_choices,
            profile_choices=profile_choices,
        )

        if not form.is_valid():
            messages.error(request, "Select at least one stream and target profile.")
            return redirect(f"{reverse('cameras:go2rtc_manager')}?instance={instance.pk}")

        selected = form.cleaned_data["stream_names"]
        profile = get_object_or_404(
            Go2RTCGridProfile,
            pk=int(form.cleaned_data["profile_id"]),
            is_active=True,
        )
        created_count = 0
        updated_count = 0

        for stream_name in selected:
            _, created = upsert_go2rtc_grid_item(
                profile=profile,
                instance=instance,
                stream_name=stream_name,
                title=stream_name,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        messages.success(
            request,
            f"Added to profile {profile.name}: {created_count} new, {updated_count} updated.",
        )
        log_audit_event(
            request=request,
            action="update",
            target=profile,
            after_state={
                "profile_id": profile.pk,
                "instance_id": instance.pk,
                "selected_streams": selected,
                "created_count": created_count,
                "updated_count": updated_count,
            },
            metadata={"operation": "go2rtc_bulk_add_streams"},
        )
        return redirect(
            f"{reverse('cameras:go2rtc_manager')}?instance={instance.pk}&profile={profile.pk}"
        )


class AddGo2RTCGridProfileView(LoginRequiredMixin, CapabilityRequiredMixin, RoleRequiredMixin, View):
    required_capability = "go2rtc_manager"
    required_roles = (ROLE_OPERATOR,)

    def post(self, request, *args, **kwargs):
        form = Go2RTCGridProfileForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid profile input.")
            return redirect(f"{reverse('cameras:go2rtc_manager')}?tab=setup")

        clean = form.cleaned_data
        existing_profile = Go2RTCGridProfile.objects.filter(name=clean["name"].strip()).first()
        before_state = None
        if existing_profile is not None:
            before_state = {
                "description": existing_profile.description,
                "is_active": existing_profile.is_active,
            }

        profile, created = Go2RTCGridProfile.objects.update_or_create(
            name=clean["name"].strip(),
            defaults={
                "description": clean["description"].strip(),
                "is_active": True,
            },
        )
        log_audit_event(
            request=request,
            action="create" if created else "update",
            target=profile,
            before_state=before_state,
            after_state={
                "description": profile.description,
                "is_active": profile.is_active,
            },
            metadata={"operation": "go2rtc_profile_upsert"},
        )
        messages.success(request, f"Profile {'created' if created else 'updated'}: {profile.name}")
        return redirect(
            f"{reverse('cameras:go2rtc_manager')}?tab=setup&profile={profile.pk}"
        )


class Go2RTCProfileGridView(LoginRequiredMixin, CapabilityRequiredMixin, TemplateView):
    template_name = "cameras/go2rtc_profile_grid.html"
    required_capability = "go2rtc_manager"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profiles = Go2RTCGridProfile.objects.filter(is_active=True).order_by("name")
        profile = get_object_or_404(Go2RTCGridProfile, pk=kwargs["pk"], is_active=True)
        ctx["profiles"] = profiles
        ctx["profile"] = profile
        ctx["tiles"] = get_go2rtc_profile_tiles(profile)
        return ctx


class RemoveGo2RTCProfileItemView(LoginRequiredMixin, CapabilityRequiredMixin, RoleRequiredMixin, View):
    required_capability = "go2rtc_manager"
    required_roles = (ROLE_OPERATOR,)

    def post(self, request, pk: int, *args, **kwargs):
        item = get_object_or_404(Go2RTCGridItem, pk=pk, is_active=True)
        before_state = {
            "profile_id": item.profile_id,
            "instance_id": item.instance_id,
            "stream_name": item.stream_name,
            "title": item.title,
            "is_active": item.is_active,
        }
        item.is_active = False
        item.save(update_fields=["is_active", "updated_at"])
        log_audit_event(
            request=request,
            action="delete",
            target=item,
            before_state=before_state,
            after_state={**before_state, "is_active": False},
            metadata={"operation": "go2rtc_profile_item_remove"},
        )
        messages.success(request, f"Removed stream from profile {item.profile.name}: {item.title or item.stream_name}")
        return redirect(reverse("cameras:go2rtc_profile_grid", kwargs={"pk": item.profile_id}))


class CameraMapView(LoginRequiredMixin, TemplateView):
    template_name = "cameras/map.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        map_settings = _effective_map_settings_for_user(self.request.user)
        ctx["countries"] = get_country_choices()
        ctx["source_types"] = SourceType.choices
        ctx["map_disable_clustering_at_zoom"] = map_settings["disable_clustering_at_zoom"]
        ctx["map_marker_limit"] = map_settings["marker_limit"]
        ctx["status_stale_minutes"] = map_settings["status_stale_minutes"]
        ctx["popup_close_on_mouseout"] = map_settings["popup_close_on_mouseout"]
        return ctx


class CameraMapDataView(LoginRequiredMixin, View):
    """Return map markers JSON for Leaflet rendering."""

    @staticmethod
    def _parse_float(value: str | None) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_int(value: str | None, *, default: int, min_value: int, max_value: int) -> int:
        try:
            parsed = int(str(value))
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, parsed))

    def get(self, request, *args, **kwargs):
        map_settings = _effective_map_settings_for_user(request.user)
        source = request.GET.get("source") or None
        country = request.GET.get("country") or None

        online_raw = request.GET.get("online", "")
        is_online = None
        if online_raw in {"0", "1"}:
            is_online = online_raw == "1"

        min_lat = self._parse_float(request.GET.get("min_lat"))
        max_lat = self._parse_float(request.GET.get("max_lat"))
        min_lng = self._parse_float(request.GET.get("min_lng"))
        max_lng = self._parse_float(request.GET.get("max_lng"))
        limit = self._parse_int(
            request.GET.get("limit"),
            default=int(map_settings["marker_limit"]),
            min_value=100,
            max_value=5000,
        )
        include_preview = request.GET.get("preview") in {"1", "true", "yes"}
        include_go2rtc_instances = request.GET.get("go2rtc") in {"1", "true", "yes"}

        payload = get_camera_map_markers(
            source_type=source,
            country=country,
            is_online=is_online,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lng=min_lng,
            max_lng=max_lng,
            limit=limit,
            include_preview=include_preview,
            include_go2rtc_instances=include_go2rtc_instances,
        )
        payload["limit"] = limit
        return JsonResponse(payload)


class HtmxCameraMapPanelView(LoginRequiredMixin, View):
    """Return camera detail panel fragment for map marker clicks."""

    def get(self, request, pk: int, *args, **kwargs):
        map_settings = _effective_map_settings_for_user(request.user)
        camera = get_object_or_404(Camera, pk=pk, is_active=True)
        stale_cutoff = timezone.now() - timedelta(minutes=int(map_settings["status_stale_minutes"]))
        status_is_stale = camera.last_checked is None or camera.last_checked < stale_cutoff
        html = render_to_string(
            "htmx/cameras/_map_panel.html",
            {
                "camera": camera,
                "display_title": build_camera_display_title(
                    source_type=camera.source_type,
                    title=camera.title,
                    city=camera.city,
                    country=camera.country,
                    camera_id=camera.pk,
                ),
                "stream_id": extract_camera_stream_id(
                    source_type=camera.source_type,
                    title=camera.title,
                ),
                "status_is_stale": status_is_stale,
                "status_stale_minutes": map_settings["status_stale_minutes"],
            },
            request=request,
        )
        return HttpResponse(html)


class HtmxGo2RTCInstanceMapPanelView(LoginRequiredMixin, View):
    """Return go2rtc instance panel fragment for map marker clicks."""

    PAGE_SIZE_CHOICES = (10, 25, 50)
    DEFAULT_PAGE_SIZE = 25

    def _resolve_page_size(self, request) -> int:
        try:
            value = int(request.GET.get("per_page", self.DEFAULT_PAGE_SIZE))
        except (TypeError, ValueError):
            return self.DEFAULT_PAGE_SIZE
        return value if value in self.PAGE_SIZE_CHOICES else self.DEFAULT_PAGE_SIZE

    @staticmethod
    def _all_stream_rows(instance: Go2RTCInstance) -> list[dict[str, object]]:
        streams = list(
            instance.streams.exclude(stream_name__iexact="xdebug").order_by("stream_name")
        )
        if streams:
            return [
                {
                    "stream_name": stream.stream_name,
                    "producers_count": stream.producers_count,
                    "consumers_count": stream.consumers_count,
                }
                for stream in streams
            ]

        fallback_streams, _error = fetch_go2rtc_streams(base_url=instance.base_url, use_cache=True)
        return [
            {
                "stream_name": row.get("name", ""),
                "producers_count": row.get("producers", 0),
                "consumers_count": row.get("consumers", 0),
            }
            for row in fallback_streams
            if str(row.get("name") or "").strip()
            and str(row.get("name") or "").strip().lower() != "xdebug"
        ]

    def get(self, request, pk: int, *args, **kwargs):
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

        instance = get_object_or_404(Go2RTCInstance, pk=pk, is_active=True)
        all_streams = self._all_stream_rows(instance)
        page_size = self._resolve_page_size(request)
        paginator = Paginator(all_streams, page_size)
        try:
            streams_page = paginator.page(request.GET.get("page", 1))
        except PageNotAnInteger:
            streams_page = paginator.page(1)
        except EmptyPage:
            streams_page = paginator.page(paginator.num_pages)

        selected_stream_name = (request.GET.get("stream_name") or "").strip()
        selected_stream = next(
            (row for row in all_streams if row["stream_name"] == selected_stream_name), None
        )

        stream_urls = None
        if selected_stream is not None:
            stream_urls = build_go2rtc_stream_urls(instance.base_url, str(selected_stream["stream_name"]))

        html = render_to_string(
            "htmx/cameras/_go2rtc_instance_panel.html",
            {
                "instance": instance,
                "streams_page": streams_page,
                "streams": streams_page.object_list,
                "stream_total": len(all_streams),
                "page_size": page_size,
                "page_size_choices": self.PAGE_SIZE_CHOICES,
                "selected_stream": selected_stream,
                "selected_stream_urls": stream_urls,
                "selected_stream_name": selected_stream_name,
                "sync_status_display": instance.get_last_sync_status_display(),
                "sync_status_color": (
                    "success"
                    if instance.last_sync_status == Go2RTCInstance.LastSyncStatus.SUCCESS
                    else "warning"
                    if instance.last_sync_status == Go2RTCInstance.LastSyncStatus.UNAUTHORIZED
                    else "danger"
                    if instance.last_sync_status == Go2RTCInstance.LastSyncStatus.FAILED
                    else "secondary"
                ),
            },
            request=request,
        )
        return HttpResponse(html)


class HtmxGo2RTCInstanceStreamPlayerView(LoginRequiredMixin, View):
    """Return a go2rtc iframe player fragment for a selected instance stream."""

    def get(self, request, pk: int, *args, **kwargs):
        instance = get_object_or_404(Go2RTCInstance, pk=pk, is_active=True)
        stream_name = (request.GET.get("stream_name") or "").strip()
        if not stream_name:
            return HttpResponse("", status=400)

        urls = build_go2rtc_stream_urls(instance.base_url, stream_name)
        html = render_to_string(
            "htmx/cameras/_go2rtc_instance_player.html",
            {
                "title": stream_name,
                "stream_name": stream_name,
                "go2rtc_src": urls.get("webrtc_embed") or urls.get("viewer") or urls.get("webrtc") or "",
            },
            request=request,
        )
        return HttpResponse(html)


class CameraLocationSuggestionsView(LoginRequiredMixin, View):
    """Return location suggestions (country/city) for map autocomplete."""

    def get(self, request, *args, **kwargs):
        from apps.cameras.services import get_location_suggestions

        query = request.GET.get("q", "").strip()
        limit = int(request.GET.get("limit", 20))
        suggestions = get_location_suggestions(query, limit=limit)
        return JsonResponse({"suggestions": suggestions})


class HtmxCameraCheckStreamView(LoginRequiredMixin, View):
    """
    POST: dispatch background stream check, return 'Checking...' badge with HTMX polling.
    GET:  return current status badge; stops polling once last_checked >= check_started.
    """

    def post(self, request, pk: int, *args, **kwargs):
        from apps.cameras.tasks import check_single_camera_status

        camera = get_object_or_404(Camera, pk=pk, is_active=True)
        check_started = int(timezone.now().timestamp())
        task = check_single_camera_status.delay(pk)
        logger.info("HtmxCameraCheckStreamView: dispatched check for camera %d task=%s", pk, task.id)
        html = render_to_string(
            "htmx/cameras/_status_badge.html",
            {
                "camera": camera,
                "checking": True,
                "check_started": check_started,
                "task_id": task.id,
            },
            request=request,
        )
        return HttpResponse(html)

    def get(self, request, pk: int, *args, **kwargs):
        camera = get_object_or_404(Camera, pk=pk, is_active=True)
        check_started_str = request.GET.get("check_started", "")
        checking = False
        MAX_POLL_SECONDS = 30  # stop polling after 30 s regardless of task state
        if check_started_str:
            try:
                check_started_ts = int(check_started_str)
                now_ts = int(timezone.now().timestamp())
                elapsed = now_ts - check_started_ts
                if elapsed <= MAX_POLL_SECONDS and (
                    camera.last_checked is None
                    or int(camera.last_checked.timestamp()) < check_started_ts
                ):
                    checking = True  # Task not finished yet — keep polling
                elif elapsed > MAX_POLL_SECONDS:
                    logger.warning(
                        "HtmxCameraCheckStreamView: polling timed out for camera %d after %ds",
                        pk,
                        elapsed,
                    )
            except (ValueError, TypeError):
                pass
        # Re-fetch from DB to get fresh is_online / last_checked after task completes
        camera.refresh_from_db()
        html = render_to_string(
            "htmx/cameras/_status_badge.html",
            {"camera": camera, "checking": checking, "check_started": check_started_str},
            request=request,
        )
        return HttpResponse(html)


import logging as _log
logger = _log.getLogger(__name__)

_DIRECT_STREAM_HINTS = ("axis-cgi", "video.cgi", ".mjpeg", ".mjpg", "/videostream", "rtsp://")


class ResolveWindyStreamView(LoginRequiredMixin, View):
    """Resolve a fresh playable stream URL for a Windy camera and return a player HTML partial.

    On each call:
    - Run async _resolve_direct_stream_url against the Windy stream page.
    - Return an HTMX-compatible HTML partial (HLS player or iframe).

    The camera's stored stream_url is always the stable Windy embed page
    (https://webcams.windy.com/webcams/stream/<id>). The resolved m3u8/MJPEG
    URL is never written to the database — it is always fetched fresh so
    that rotating IPCamLive stream IDs and server addresses do not go stale.
    """

    def get(self, request, pk: int) -> HttpResponse:
        from asgiref.sync import async_to_sync
        from apps.scraping.http import build_client
        from apps.scraping.parsers.windy import _resolve_direct_stream_url

        camera = get_object_or_404(Camera, pk=pk, source_type=SourceType.WINDY)
        webcam_id = str((camera.source_payload or {}).get("webcam_id") or "").strip()
        fallback_url = (
            f"https://webcams.windy.com/webcams/stream/{webcam_id}"
            if webcam_id
            else (camera.stream_url or "")
        )

        resolved_url = ""
        if webcam_id:
            try:
                async def _resolve() -> str:
                    async with build_client() as client:
                        return await _resolve_direct_stream_url(client, webcam_id)

                resolved_url = async_to_sync(_resolve)() or ""
            except Exception:
                logger.exception("ResolveWindyStreamView: failed to resolve stream for camera %d", pk)

        stream_url = resolved_url or fallback_url
        stream_url_lower = stream_url.lower()
        is_hls = ".m3u8" in stream_url_lower
        is_direct_stream = not is_hls and any(h in stream_url_lower for h in _DIRECT_STREAM_HINTS)

        return HttpResponse(
            render_to_string(
                "htmx/cameras/_windy_player.html",
                {
                    "camera": camera,
                    "resolved_url": stream_url,
                    "is_hls": is_hls,
                    "is_direct_stream": is_direct_stream,
                },
                request=request,
            )
        )


class HtmxCameraListView(LoginRequiredMixin, ListView):
    """Returns only the camera table partial for HTMX swaps."""

    model = Camera
    template_name = "htmx/cameras/_camera_table.html"
    context_object_name = "cameras"
    paginate_by = CAMERA_LIST_PAGE_SIZE

    def get_queryset(self):
        qs = Camera.objects.filter(is_active=True).order_by("-created_at")
        return _apply_camera_list_filters(qs, self.request)


class HtmxUnifiedPlayerView(LoginRequiredMixin, DetailView):
    """Render only the unified camera player partial for HTMX swaps."""

    model = Camera
    template_name = "htmx/cameras/_player.html"
    context_object_name = "camera"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["surveillance_mode"] = _to_bool_flag(self.request.GET.get("surveillance"))
        return ctx


class HtmxGridItemPlayerView(LoginRequiredMixin, View):
    """Render the go2rtc iframe player for a Go2RTCGridItem (surveillance grid)."""

    def get(self, request, pk: int) -> HttpResponse:
        from apps.cameras.services import build_go2rtc_stream_urls as _build_urls
        from apps.cameras.services_grid import GridItemAdapter

        grid_item = get_object_or_404(
            Go2RTCGridItem.objects.select_related("instance"),
            pk=pk,
            is_active=True,
        )
        urls = _build_urls(grid_item.instance.base_url, grid_item.stream_name)
        adapter = GridItemAdapter(grid_item, stream_urls=urls)
        ctx = {
            "camera": adapter,
            "surveillance_mode": _to_bool_flag(request.GET.get("surveillance")),
        }
        return HttpResponse(
            render_to_string("htmx/cameras/_player.html", ctx, request=request)
        )


class HtmxSurveillanceStreamListView(LoginRequiredMixin, CapabilityRequiredMixin, View):
    """Render stream list partial for Surveillance manage panel.
    
    Deferred HTMX endpoint to unblock initial page render.
    Returns HTML partial with stream table or error message.
    """
    required_capability = "surveillance"

    def get(self, request: any) -> HttpResponse:
        try:
            default_instance = get_or_create_default_private_instance()
            streams, source_error = fetch_go2rtc_streams(base_url=default_instance.base_url, use_cache=True)
        except Exception as e:
            streams = []
            source_error = f"Error fetching streams: {str(e)}"
            logger.warning("Surveillance stream list fetch failed: %s", e)
        
        ctx = {
            "go2rtc_streams": streams,
            "go2rtc_source_error": source_error,
        }
        return HttpResponse(
            render_to_string("htmx/cameras/_surveillance_stream_list.html", ctx, request=request)
        )


class HtmxSurveillanceServerHealthView(LoginRequiredMixin, CapabilityRequiredMixin, View):
    """Render a live go2rtc server status badge for the Surveillance toolbar."""

    required_capability = "surveillance"

    def get(self, request: any) -> HttpResponse:
        go2rtc_base_url = ""
        source_error: str | None = None

        try:
            default_instance = get_or_create_default_private_instance()
            go2rtc_base_url = default_instance.base_url
            _, source_error = fetch_go2rtc_streams(
                base_url=go2rtc_base_url,
                timeout_seconds=1.5,
                use_cache=False,
            )
        except Exception as exc:
            source_error = f"Error checking server status: {str(exc)}"
            logger.warning("Surveillance server health check failed: %s", exc)

        ctx = {
            "go2rtc_base_url": go2rtc_base_url,
            "go2rtc_source_error": source_error,
            "go2rtc_is_online": source_error is None,
        }
        return HttpResponse(
            render_to_string("htmx/cameras/_surveillance_server_health.html", ctx, request=request)
        )
