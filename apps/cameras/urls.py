from __future__ import annotations

from django.urls import path

from . import views

app_name = "cameras"

urlpatterns = [
    path("", views.CameraListView.as_view(), name="list"),
    path("surveillance/", views.Go2RTCCameraGridView.as_view(), name="surveillance"),
    path("surveillance/add/", views.AddGo2RTCCameraView.as_view(), name="surveillance_add"),
    path("surveillance/<int:pk>/remove/", views.RemoveGo2RTCCameraView.as_view(), name="surveillance_remove"),
    path("map/", views.CameraMapView.as_view(), name="map"),
    path("map/data/", views.CameraMapDataView.as_view(), name="map_data"),
    path("map/locations/suggest/", views.CameraLocationSuggestionsView.as_view(), name="map_locations_suggest"),
    path("<int:pk>/", views.CameraDetailView.as_view(), name="detail"),
]
