from __future__ import annotations

from django.urls import path

from . import views

app_name = "cameras_htmx"

# Namespace registered in config/urls.py as cameras_htmx
urlpatterns = [
    path("", views.HtmxCameraListView.as_view(), name="htmx_list"),
    path("<int:pk>/player/", views.HtmxUnifiedPlayerView.as_view(), name="player"),
    path("<int:pk>/grid-player/", views.HtmxGridItemPlayerView.as_view(), name="grid_player"),
    path("map-panel/<int:pk>/", views.HtmxCameraMapPanelView.as_view(), name="map_panel"),
    path("map-panel-instance/<int:pk>/", views.HtmxGo2RTCInstanceMapPanelView.as_view(), name="map_panel_instance"),
    path("map-panel-instance/<int:pk>/stream/", views.HtmxGo2RTCInstanceStreamPlayerView.as_view(), name="map_panel_instance_stream"),
    path("<int:pk>/check-stream/", views.HtmxCameraCheckStreamView.as_view(), name="check_stream"),
    path("surveillance/server-health/", views.HtmxSurveillanceServerHealthView.as_view(), name="surveillance_server_health"),
    path("surveillance/stream-list/", views.HtmxSurveillanceStreamListView.as_view(), name="surveillance_stream_list"),
]
