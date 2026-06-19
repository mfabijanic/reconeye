from __future__ import annotations

import logging
from typing import Any

from django.db.models import Count

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
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    by_source = [
        {
            "source_type": row["source_type"],
            "label": SourceType(row["source_type"]).label
            if row["source_type"] in SourceType.values
            else row["source_type"],
            "count": row["count"],
        }
        for row in Camera.objects.filter(is_active=True)
        .values("source_type")
        .annotate(count=Count("id"))
        .order_by("source_type")
    ]

    active_jobs = list(
        ScrapeJob.objects.filter(status__in=[ScrapeJobStatus.PENDING, ScrapeJobStatus.RUNNING])
        .values("id", "source_type", "status", "total_found", "total_processed", "started_at")
        .order_by("-created_at")[:5]
    )

    stats = {
        "total": total,
        "online": online,
        "offline": offline,
        "by_country": by_country,
        "by_source": by_source,
        "active_jobs": active_jobs,
    }
    cache.set(key, stats, TTL_WARM if force else TTL_DASHBOARD)
    return stats
