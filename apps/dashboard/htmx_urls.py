from django.urls import path

from . import views

app_name = "dashboard_htmx"

urlpatterns = [
    path("stats/", views.HtmxDashboardStatsView.as_view(), name="htmx_stats"),
]
