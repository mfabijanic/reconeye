from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.cameras.models import Camera, MapUISettings, SourceType
from apps.cameras.services import get_camera_map_markers, get_country_choices
from apps.users.models import UserMapSettings


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
        if q := self.request.GET.get("q"):
            qs = qs.filter(title__icontains=q)
        if country := self.request.GET.get("country"):
            qs = qs.filter(country__iexact=country)
        if source := self.request.GET.get("source"):
            qs = qs.filter(source_type=source)
        if online := self.request.GET.get("online"):
            qs = qs.filter(is_online=online == "1")
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["countries"] = get_country_choices()
        ctx["source_types"] = SourceType.choices
        ctx["q"] = self.request.GET.get("q", "")
        ctx["selected_country"] = self.request.GET.get("country", "")
        ctx["selected_source"] = self.request.GET.get("source", "")
        ctx["selected_online"] = self.request.GET.get("online", "")
        return ctx


class CameraDetailView(LoginRequiredMixin, DetailView):
    model = Camera
    template_name = "cameras/detail.html"
    context_object_name = "camera"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        camera = self.get_object()
        
        # If title looks like a stream ID (e.g., "hr_pag03"), use city as display title
        title = camera.title or ""
        if title and any(title.lower().startswith(f"{code.lower()}_") for code in ["BA", "DO", "ES", "GR", "HR", "IE", "IT", "MK", "NL", "SI"]):
            if camera.city:
                ctx["display_title"] = f"{camera.city}, {camera.country}" if camera.country else camera.city
            else:
                ctx["display_title"] = title
        else:
            ctx["display_title"] = title or f"Camera #{camera.pk}"
        
        return ctx


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


class HtmxCameraListView(LoginRequiredMixin, ListView):
    """Returns only the camera table partial for HTMX swaps."""

    model = Camera
    template_name = "htmx/cameras/_camera_table.html"
    context_object_name = "cameras"
    paginate_by = 50

    def get_queryset(self):
        qs = Camera.objects.filter(is_active=True).order_by("-created_at")
        if q := self.request.GET.get("q"):
            qs = qs.filter(title__icontains=q)
        if country := self.request.GET.get("country"):
            qs = qs.filter(country__iexact=country)
        if source := self.request.GET.get("source"):
            qs = qs.filter(source_type=source)
        if online := self.request.GET.get("online"):
            qs = qs.filter(is_online=online == "1")
        return qs
