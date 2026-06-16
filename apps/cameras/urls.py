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
    path("go2rtc-viewer/", views.Go2RTCInstanceViewerView.as_view(), name="go2rtc_viewer"),
    path(
        "go2rtc-viewer/<int:pk>/live-metrics/",
        views.Go2RTCViewerLiveMetricsView.as_view(),
        name="go2rtc_viewer_live_metrics",
    ),
    path("go2rtc-manager/add/", views.AddGo2RTCInstanceView.as_view(), name="go2rtc_manager_add"),
    path("go2rtc-manager/profiles/add/", views.AddGo2RTCGridProfileView.as_view(), name="go2rtc_profile_add"),
    path("go2rtc-manager/<int:pk>/sync/", views.SyncGo2RTCInstanceView.as_view(), name="go2rtc_manager_sync"),
    path("go2rtc-manager/import/preview/", views.Go2RTCImportPreviewView.as_view(), name="go2rtc_import_preview"),
    path("go2rtc-manager/import/confirm/", views.Go2RTCImportConfirmView.as_view(), name="go2rtc_import_confirm"),
    path("go2rtc-manager/<int:pk>/bulk-add/", views.BulkAddGo2RTCStreamsView.as_view(), name="go2rtc_manager_bulk_add"),
    path("go2rtc-grid/<int:pk>/", views.Go2RTCProfileGridView.as_view(), name="go2rtc_profile_grid"),
    path("go2rtc-grid/items/<int:pk>/remove/", views.RemoveGo2RTCProfileItemView.as_view(), name="go2rtc_profile_item_remove"),
    path("map/", views.CameraMapView.as_view(), name="map"),
    path("map/data/", views.CameraMapDataView.as_view(), name="map_data"),
    path("map/locations/suggest/", views.CameraLocationSuggestionsView.as_view(), name="map_locations_suggest"),
    path("<int:pk>/", views.CameraDetailView.as_view(), name="detail"),
    path("<int:pk>/resolve-stream/", views.ResolveWindyStreamView.as_view(), name="resolve_stream"),
]
