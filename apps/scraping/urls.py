from django.urls import path

from . import views

app_name = "scraping"

urlpatterns = [
    path("jobs/", views.ScrapeJobListView.as_view(), name="job_list"),
    path("jobs/<int:pk>/", views.ScrapeJobDetailView.as_view(), name="job_detail"),
    path("jobs/trigger/", views.TriggerScrapeView.as_view(), name="trigger"),
    path("jobs/<int:pk>/cancel/", views.CancelScrapeView.as_view(), name="cancel"),
]
