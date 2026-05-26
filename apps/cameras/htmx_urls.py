from __future__ import annotations

from django.urls import path

from . import views

app_name = "cameras_htmx"

# Namespace registered in config/urls.py as cameras_htmx
urlpatterns = [
    path("", views.HtmxCameraListView.as_view(), name="htmx_list"),
    path("map-panel/<int:pk>/", views.HtmxCameraMapPanelView.as_view(), name="map_panel"),
]
