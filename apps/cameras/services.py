from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.common.cache import TTL_CAMERAS, versioned_key, DOMAIN_CAMERAS
from apps.cameras.models import Camera, CameraCheckLog, SourceType

logger = logging.getLogger(__name__)

CAMERA_LOG_RETENTION_DAYS = 30


def get_camera_list(
    *,
    source_type: str | None = None,
    country: str | None = None,
    city: str | None = None,
    is_online: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    from django.core.cache import cache
    from django.core.paginator import Paginator

    cache_key = versioned_key(
        DOMAIN_CAMERAS,
        f"list:src={source_type}:country={country}:city={city}:online={is_online}:page={page}",
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    qs = Camera.objects.filter(is_active=True).order_by("-created_at")
    if source_type:
        qs = qs.filter(source_type=source_type)
    if country:
        qs = qs.filter(country__iexact=country)
    if city:
        qs = qs.filter(city__icontains=city)
    if is_online is not None:
        qs = qs.filter(is_online=is_online)

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)
    result = {
        "cameras": list(page_obj.object_list.values()),
        "total": paginator.count,
        "page": page,
        "num_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }
    cache.set(cache_key, result, TTL_CAMERAS)
    return result


def get_country_choices() -> list[str]:
    from django.core.cache import cache

    key = versioned_key(DOMAIN_CAMERAS, "filters:countries")
    cached = cache.get(key)
    if cached is not None:
        return cached
    countries = list(
        Camera.objects.filter(is_active=True)
        .exclude(country="")
        .values_list("country", flat=True)
        .distinct()
        .order_by("country")
    )
    cache.set(key, countries, TTL_CAMERAS)
    return countries


def cleanup_check_logs(days: int = CAMERA_LOG_RETENTION_DAYS) -> int:
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = CameraCheckLog.objects.filter(checked_at__lt=cutoff).delete()
    logger.info("Cleaned up %d CameraCheckLog entries older than %d days", deleted, days)
    return deleted


def upsert_camera(data: dict[str, Any]) -> tuple[Camera, bool]:
    """
    Insert or update a camera by page_url + source_type (deduplication key).
    Returns (camera, created).

    Online status rules:
    - New cameras: is_online=True if they have a stream_url (they appeared on
      the source site, so they are presumed live until a check task says otherwise).
    - Existing cameras: is_online is NOT overwritten by the scraper — only
      the refresh_camera_status task should change it.
    """
    source_type = data.get("source_type")
    page_url = data.get("page_url", "")

    # Never let the scraper overwrite is_online on existing cameras.
    defaults = {
        k: v
        for k, v in data.items()
        if k not in ("source_type", "page_url", "is_online")
    }

    with transaction.atomic():
        camera, created = Camera.objects.update_or_create(
            source_type=source_type,
            page_url=page_url,
            defaults=defaults,
        )
        if created:
            # Presume online when we have a direct stream URL.
            camera.is_online = bool(data.get("stream_url", "").strip())
            camera.save(update_fields=["is_online"])
    return camera, created
