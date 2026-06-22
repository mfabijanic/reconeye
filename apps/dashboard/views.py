from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views.generic import ListView, TemplateView

from apps.dashboard.services import get_dashboard_stats
from apps.scraping.models import ScrapeJob


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["stats"] = get_dashboard_stats()
        return ctx


class HtmxDashboardStatsView(LoginRequiredMixin, TemplateView):
    template_name = "htmx/dashboard/_stats.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["stats"] = get_dashboard_stats()
        return ctx


class HtmxDashboardActiveJobsView(LoginRequiredMixin, ListView):
    template_name = "htmx/scraping/_job_row.html"
    context_object_name = "jobs"

    def get_queryset(self):
        return ScrapeJob.objects.order_by("-created_at")[:10]
