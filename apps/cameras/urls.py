from __future__ import annotations

from django.urls import path

from . import views

app_name = "cameras"

urlpatterns = [
    path("", views.CameraListView.as_view(), name="list"),
    path("<int:pk>/", views.CameraDetailView.as_view(), name="detail"),
]
