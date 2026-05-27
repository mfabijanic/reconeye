from django.urls import path

from . import views

app_name = "scraping_htmx"

urlpatterns = [
    path("jobs/", views.HtmxJobListView.as_view(), name="htmx_jobs"),
    path("jobs/<int:pk>/row/", views.HtmxJobRowView.as_view(), name="htmx_job_row"),
    path("nav/job-status/", views.HtmxNavJobStatusView.as_view(), name="nav_job_status"),
]
