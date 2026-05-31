from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import CharField, F, Q
from django.db.models.functions import Cast, Lower, Trim
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.cameras.forms import Go2RTCCameraForm
from apps.cameras.models import Camera, MapUISettings, SourceType
from apps.cameras.services import (
    build_camera_display_title,
    ensure_go2rtc_camera_stream_urls,
    extract_camera_stream_id,
    fetch_go2rtc_streams,
    get_camera_map_markers,
    get_country_choices,
    normalize_go2rtc_base_url,
    upsert_go2rtc_camera,
)
from apps.users.models import UserMapSettings


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
    paginate_by = 50

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


class Go2RTCCameraGridView(LoginRequiredMixin, TemplateView):
    template_name = "cameras/surveillance.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base_url = normalize_go2rtc_base_url()
        streams, source_error = fetch_go2rtc_streams(base_url=base_url)
        selected_cameras = (
            Camera.objects.filter(source_type=SourceType.GO2RTC, is_active=True)
            .order_by("title", "id")
        )
        selected_cameras = [ensure_go2rtc_camera_stream_urls(camera) for camera in selected_cameras]
        ctx["go2rtc_base_url"] = base_url
        ctx["go2rtc_streams"] = streams
        ctx["go2rtc_source_error"] = source_error
        ctx["selected_cameras"] = selected_cameras
        ctx["go2rtc_form"] = Go2RTCCameraForm()
        return ctx


class AddGo2RTCCameraView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        form = Go2RTCCameraForm(request.POST)
        if not form.is_valid():
            error_html = '<div class="alert alert-danger alert-dismissible fade show" role="alert">'
            error_html += "Invalid input for the go2rtc camera."
            error_html += '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>'
            return HttpResponse(error_html)

        stream_name = form.cleaned_data["stream_name"].strip()
        title = form.cleaned_data["title"].strip()
        camera, created = upsert_go2rtc_camera(stream_name=stream_name, title=title)
        
        if created:
            message = f"Added camera: {camera.title}"
            alert_class = "alert-success"
        else:
            message = f"Updated camera: {camera.title}"
            alert_class = "alert-info"
        
        success_html = f'<div class="alert {alert_class} alert-dismissible fade show" role="alert">'
        success_html += message
        success_html += '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>'
        return HttpResponse(success_html)


class RemoveGo2RTCCameraView(LoginRequiredMixin, View):
    def post(self, request, pk: int, *args, **kwargs):
        camera = get_object_or_404(Camera, pk=pk, source_type=SourceType.GO2RTC)
        camera.is_active = False
        camera.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"Removed camera: {camera.title or camera.pk}")
        return redirect("cameras:surveillance")


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


class HtmxCameraListView(LoginRequiredMixin, ListView):
    """Returns only the camera table partial for HTMX swaps."""

    model = Camera
    template_name = "htmx/cameras/_camera_table.html"
    context_object_name = "cameras"
    paginate_by = 50

    def get_queryset(self):
        qs = Camera.objects.filter(is_active=True).order_by("-created_at")
        return _apply_camera_list_filters(qs, self.request)
