from __future__ import annotations

from datetime import UTC, datetime

from django.contrib import admin as django_admin
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from apps.common.celery_activity import get_active_task_summary


class HealthView(View):
    def get(self, request):
        return JsonResponse({"status": "ok"})


class ReadinessView(View):
    def get(self, request):
        from django.db import connection

        try:
            connection.ensure_connection()
            db_ok = True
        except Exception:
            db_ok = False
        status = "ok" if db_ok else "degraded"
        return JsonResponse({"status": status, "db": db_ok}, status=200 if db_ok else 503)


class HtmxNavNotificationsView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.scraping.models import ScrapeJob, ScrapeJobStatus

        active_job_count = ScrapeJob.objects.filter(
            status__in=[ScrapeJobStatus.RUNNING, ScrapeJobStatus.PENDING]
        ).count()
        recent_jobs = list(
            ScrapeJob.objects.filter(
                status__in=[ScrapeJobStatus.SUCCESS, ScrapeJobStatus.FAILED]
            )
            .order_by("-finished_at", "-created_at")[:3]
        )
        task_summary = get_active_task_summary(limit=3)
        last_seen_at = task_summary.get("last_seen_at")
        last_seen_at_dt = (
            datetime.fromtimestamp(last_seen_at, tz=UTC)
            if isinstance(last_seen_at, (int, float))
            else None
        )

        html = render_to_string(
            "htmx/common/_nav_notifications_panel.html",
            {
                "active_job_count": active_job_count,
                "active_task_count": task_summary.get("active_count", 0),
                "show_notification_dot": active_job_count > 0 or int(task_summary.get("active_count", 0)) > 0,
                "recent_jobs": recent_jobs,
                "top_tasks": task_summary.get("top_tasks", []),
                "extra_task_types": task_summary.get("extra_task_types", 0),
                "last_seen_at_dt": last_seen_at_dt,
            },
            request=request,
        )
        return HttpResponse(html)


class AdminHubView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "common/admin_hub.html"

    def test_func(self) -> bool:
        return self.request.user.is_staff

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["admin_app_list"] = django_admin.site.get_app_list(self.request)
        return ctx
