from __future__ import annotations

from django.urls import path

from . import views

app_name = "cameras"

urlpatterns = [
    path("", views.CameraListView.as_view(), name="list"),
    path("surveillance/", views.Go2RTCCameraGridView.as_view(), name="surveillance"),
    path("surveillance/add/", views.AddGo2RTCCameraView.as_view(), name="surveillance_add"),
    path("surveillance/<int:pk>/remove/", views.RemoveGo2RTCCameraView.as_view(), name="surveillance_remove"),
    path("go2rtc-manager/", views.Go2RTCManagerView.as_view(), name="go2rtc_manager"),
    path("go2rtc-manager/add/", views.AddGo2RTCInstanceView.as_view(), name="go2rtc_manager_add"),
    path("go2rtc-manager/<int:pk>/sync/", views.SyncGo2RTCInstanceView.as_view(), name="go2rtc_manager_sync"),
    path("go2rtc-manager/<int:pk>/bulk-add/", views.BulkAddGo2RTCStreamsView.as_view(), name="go2rtc_manager_bulk_add"),
    path("map/", views.CameraMapView.as_view(), name="map"),
    path("map/data/", views.CameraMapDataView.as_view(), name="map_data"),
    path("map/locations/suggest/", views.CameraLocationSuggestionsView.as_view(), name="map_locations_suggest"),
    path("<int:pk>/", views.CameraDetailView.as_view(), name="detail"),
    path("<int:pk>/resolve-stream/", views.ResolveWindyStreamView.as_view(), name="resolve_stream"),
]
