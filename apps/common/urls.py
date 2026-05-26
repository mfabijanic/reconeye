from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("readiness/", views.ReadinessView.as_view(), name="readiness"),
]
