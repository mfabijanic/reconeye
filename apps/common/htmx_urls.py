from django.urls import path

from . import views

app_name = "common_htmx"

urlpatterns = [
    path("nav/notifications/", views.HtmxNavNotificationsView.as_view(), name="nav_notifications"),
]
