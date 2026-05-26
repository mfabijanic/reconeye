from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView, ListView

from apps.cameras.models import Camera, SourceType
from apps.cameras.services import get_camera_list, get_country_choices


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
