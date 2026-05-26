from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views.generic import TemplateView

from apps.dashboard.services import get_dashboard_stats


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
