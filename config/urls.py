from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.common.views import HealthView, ReadinessView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("users/", include("apps.users.urls", namespace="users")),
    path("cameras/", include("apps.cameras.urls", namespace="cameras")),
    path("scraping/", include("apps.scraping.urls", namespace="scraping")),
    path("dashboard/", include("apps.dashboard.urls", namespace="dashboard")),
    # HTMX partial endpoints
    path("htmx/cameras/", include("apps.cameras.htmx_urls", namespace="cameras_htmx")),
    path("htmx/scraping/", include("apps.scraping.htmx_urls", namespace="scraping_htmx")),
    path("htmx/dashboard/", include("apps.dashboard.htmx_urls", namespace="dashboard_htmx")),
    # Health
    path("health/", HealthView.as_view(), name="health"),
    path("readiness/", ReadinessView.as_view(), name="readiness"),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns

    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
