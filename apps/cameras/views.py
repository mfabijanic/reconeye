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
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.cameras.forms import Go2RTCBulkAddForm, Go2RTCCameraForm, Go2RTCInstanceForm
from apps.cameras.models import Camera, Go2RTCConfigSnapshot, Go2RTCInstance, Go2RTCStream, MapUISettings, SourceType
from apps.cameras.services import (
    build_config_diff_rows,
    build_camera_display_title,
    ensure_go2rtc_camera_stream_urls,
    extract_camera_stream_id,
    fetch_go2rtc_streams,
    get_camera_map_markers,
    get_country_choices,
    normalize_go2rtc_base_url,
    sync_go2rtc_instance,
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


class Go2RTCManagerView(LoginRequiredMixin, TemplateView):
    template_name = "cameras/go2rtc_manager.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        instances = Go2RTCInstance.objects.filter(is_active=True).order_by("name")

        selected_instance = None
        selected_id = self.request.GET.get("instance")
        if selected_id:
            try:
                selected_instance = instances.filter(pk=int(selected_id)).first()
            except (TypeError, ValueError):
                selected_instance = None
        if selected_instance is None:
            selected_instance = instances.first()

        streams_qs = Go2RTCStream.objects.none()
        latest_config = None
        config_history = Go2RTCConfigSnapshot.objects.none()
        compare_from = None
        compare_to = None
        diff_rows: list[dict[str, str]] = []
        stream_choices: list[tuple[str, str]] = []
        if selected_instance is not None:
            streams_qs = selected_instance.streams.order_by("stream_name")
            latest_config = selected_instance.config_snapshots.order_by("-fetched_at").first()
            config_history = selected_instance.config_snapshots.order_by("-fetched_at", "-id")[:50]
            stream_choices = [(s.stream_name, s.stream_name) for s in streams_qs]

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

        ctx["instances"] = instances
        ctx["selected_instance"] = selected_instance
        ctx["streams"] = streams_qs
        ctx["latest_config"] = latest_config
        ctx["config_history"] = config_history
        ctx["compare_from"] = compare_from
        ctx["compare_to"] = compare_to
        ctx["diff_rows"] = diff_rows
        ctx["instance_form"] = kwargs.get("instance_form") or Go2RTCInstanceForm()
        ctx["bulk_form"] = kwargs.get("bulk_form") or Go2RTCBulkAddForm(stream_choices=stream_choices)
        return ctx


class AddGo2RTCInstanceView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        form = Go2RTCInstanceForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid go2rtc instance input.")
            return redirect("cameras:go2rtc_manager")

        clean = form.cleaned_data
        instance, created = Go2RTCInstance.objects.update_or_create(
            name=clean["name"].strip(),
            defaults={
                "scheme": clean["scheme"],
                "host": clean["host"].strip(),
                "port": int(clean["port"]),
                "is_active": True,
            },
        )

        stream_count, error = sync_go2rtc_instance(instance)
        if error:
            messages.warning(request, f"Instance saved, but sync failed: {error}")
        else:
            action = "added" if created else "updated"
            messages.success(request, f"go2rtc instance {action}. Synced {stream_count} streams.")
        return redirect(f"{reverse('cameras:go2rtc_manager')}?instance={instance.pk}")


class SyncGo2RTCInstanceView(LoginRequiredMixin, View):
    def post(self, request, pk: int, *args, **kwargs):
        instance = get_object_or_404(Go2RTCInstance, pk=pk, is_active=True)
        stream_count, error = sync_go2rtc_instance(instance)
        if error:
            messages.error(request, f"Sync failed for {instance.name}: {error}")
        else:
            messages.success(request, f"Sync completed for {instance.name}. {stream_count} streams available.")
        return redirect(f"{reverse('cameras:go2rtc_manager')}?instance={instance.pk}")


class BulkAddGo2RTCStreamsView(LoginRequiredMixin, View):
    def post(self, request, pk: int, *args, **kwargs):
        instance = get_object_or_404(Go2RTCInstance, pk=pk, is_active=True)
        streams_qs = instance.streams.order_by("stream_name")
        stream_choices = [(s.stream_name, s.stream_name) for s in streams_qs]
        form = Go2RTCBulkAddForm(request.POST, stream_choices=stream_choices)

        if not form.is_valid():
            messages.error(request, "Select at least one stream.")
            return redirect(f"{reverse('cameras:go2rtc_manager')}?instance={instance.pk}")

        selected = form.cleaned_data["stream_names"]
        created_count = 0
        updated_count = 0

        for stream_name in selected:
            _, created = upsert_go2rtc_camera(
                stream_name=stream_name,
                title=stream_name,
                base_url=instance.base_url,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        messages.success(
            request,
            f"Added to surveillance grid: {created_count} new, {updated_count} updated.",
        )
        return redirect(f"{reverse('cameras:go2rtc_manager')}?instance={instance.pk}")


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
    paginate_by = 50

    def get_queryset(self):
        qs = Camera.objects.filter(is_active=True).order_by("-created_at")
        return _apply_camera_list_filters(qs, self.request)
