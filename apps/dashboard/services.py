from __future__ import annotations

import logging
from typing import Any

from apps.common.cache import TTL_DASHBOARD, TTL_WARM, versioned_key, DOMAIN_DASHBOARD

logger = logging.getLogger(__name__)


def get_dashboard_stats(*, force: bool = False) -> dict[str, Any]:
    from django.core.cache import cache

    key = versioned_key(DOMAIN_DASHBOARD, "stats")
    if not force:
        cached = cache.get(key)
        if cached is not None:
            return cached

    from apps.cameras.models import Camera, SourceType
    from apps.scraping.models import ScrapeJob, ScrapeJobStatus

    total = Camera.objects.filter(is_active=True).count()
    online = Camera.objects.filter(is_active=True, is_online=True).count()
    offline = total - online

    by_country = list(
        Camera.objects.filter(is_active=True)
        .exclude(country="")
        .values("country")
        .annotate(count=__import__("django.db.models", fromlist=["Count"]).Count("id"))
        .order_by("-count")[:10]
    )

    active_jobs = list(
        ScrapeJob.objects.filter(status__in=[ScrapeJobStatus.PENDING, ScrapeJobStatus.RUNNING])
        .values("id", "source_type", "status", "total_found", "total_processed", "started_at")
        .order_by("-created_at")[:5]
    )

    insecam_total = Camera.objects.filter(
        is_active=True, source_type=SourceType.INSECAM
    ).count()
    wuc_total = Camera.objects.filter(
        is_active=True, source_type=SourceType.WHATSUPCAMS
    ).count()

    stats = {
        "total": total,
        "online": online,
        "offline": offline,
        "by_country": by_country,
        "active_jobs": active_jobs,
        "insecam_total": insecam_total,
        "wuc_total": wuc_total,
    }
    cache.set(key, stats, TTL_WARM if force else TTL_DASHBOARD)
    return stats
