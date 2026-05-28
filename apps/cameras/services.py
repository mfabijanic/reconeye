from __future__ import annotations

import logging
import time
from typing import Any

from django.db import models, transaction
from django.utils import timezone

from apps.common.cache import TTL_CAMERAS, versioned_key, DOMAIN_CAMERAS
from apps.cameras.models import Camera, CameraCheckLog, SourceType

logger = logging.getLogger(__name__)

CAMERA_LOG_RETENTION_DAYS = 30
WUC_STREAM_ID_PREFIXES = ("ba_", "do_", "es_", "gr_", "hr_", "ie_", "it_", "mk_", "nl_", "si_")


def is_whatsupcams_stream_id(value: str | None) -> bool:
    text = (value or "").strip().lower()
    return bool(text) and text.startswith(WUC_STREAM_ID_PREFIXES)


def build_camera_display_title(
    *,
    source_type: str,
    title: str | None,
    city: str | None,
    country: str | None,
    camera_id: int | None = None,
) -> str:
    raw_title = (title or "").strip()
    raw_city = (city or "").strip()
    raw_country = (country or "").strip()

    if source_type == SourceType.WHATSUPCAMS and is_whatsupcams_stream_id(raw_title):
        if raw_city and raw_country:
            return f"{raw_city}, {raw_country}"
        if raw_city:
            return raw_city

    if raw_title:
        return raw_title

    if camera_id is not None:
        return f"Camera #{camera_id}"
    return "Camera"


def extract_camera_stream_id(*, source_type: str, title: str | None) -> str | None:
    raw_title = (title or "").strip()
    if source_type == SourceType.WHATSUPCAMS and is_whatsupcams_stream_id(raw_title):
        return raw_title
    return None


def get_location_suggestions(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Get location suggestions (country/city combos) for autocomplete.
    
    Aggregates geolocated cameras by country+city and returns centroids.
    """
    from django.core.cache import cache
    
    if not query or len(query.strip()) < 2:
        return []
    
    cache_key = versioned_key(DOMAIN_CAMERAS, f"locations:suggest:{query.lower()}")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    
    q = query.strip().lower()
    qs = (
        Camera.objects.filter(
            is_active=True,
            latitude__isnull=False,
            longitude__isnull=False,
        )
        .exclude(latitude=0, longitude=0)
        .filter(
            models.Q(country__icontains=q)
            | models.Q(city__icontains=q)
        )
        .values("country", "city")
        .annotate(
            lat=models.Avg("latitude"),
            lng=models.Avg("longitude"),
            count=models.Count("id"),
        )
        .order_by("-count")[: limit]
    )
    
    result = [
        {
            "country": item["country"],
            "city": item["city"],
            "latitude": item["lat"],
            "longitude": item["lng"],
            "camera_count": item["count"],
            "label": f"{item['city']}, {item['country']}",
        }
        for item in qs
    ]
    
    cache.set(cache_key, result, TTL_CAMERAS)
    return result


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


def get_camera_map_markers(
    *,
    source_type: str | None = None,
    country: str | None = None,
    is_online: bool | None = None,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lng: float | None = None,
    max_lng: float | None = None,
    limit: int = 1500,
    include_preview: bool = False,
) -> dict[str, Any]:
    """Return cached marker payload for the map view.

    Returns:
        {
            "markers": list[dict[str, Any]],
            "count": int,
            "total": int,
            "truncated": bool,
        }
    """
    from django.core.cache import cache

    started = time.monotonic()

    cache_key = versioned_key(
        DOMAIN_CAMERAS,
        "map:"
        f"src={source_type}:country={country}:online={is_online}:"
        f"min_lat={min_lat}:max_lat={max_lat}:min_lng={min_lng}:max_lng={max_lng}:"
        f"limit={limit}:preview={include_preview}:display=v2",
    )
    cached = cache.get(cache_key)
    if cached is not None:
        logger.info(
            "camera_map_data cache_hit=1 count=%s total=%s truncated=%s elapsed_ms=%.2f",
            cached.get("count"),
            cached.get("total"),
            cached.get("truncated"),
            (time.monotonic() - started) * 1000,
        )
        return cached

    qs = Camera.objects.filter(is_active=True, latitude__isnull=False, longitude__isnull=False)
    # In source data, (0, 0) typically means unknown geolocation.
    qs = qs.exclude(latitude=0, longitude=0)

    if source_type:
        qs = qs.filter(source_type=source_type)
    if country:
        qs = qs.filter(country__iexact=country)
    if is_online is not None:
        qs = qs.filter(is_online=is_online)
    if min_lat is not None:
        qs = qs.filter(latitude__gte=min_lat)
    if max_lat is not None:
        qs = qs.filter(latitude__lte=max_lat)
    if min_lng is not None:
        qs = qs.filter(longitude__gte=min_lng)
    if max_lng is not None:
        qs = qs.filter(longitude__lte=max_lng)

    total = qs.count()

    fields = [
        "id",
        "title",
        "source_type",
        "country",
        "city",
        "latitude",
        "longitude",
        "stream_url",
        "is_online",
        "has_partial_metadata",
        "last_checked",
    ]
    if include_preview:
        fields.append("preview_image")

    markers = list(qs.values(*fields)[:limit])
    for marker in markers:
        marker["display_title"] = build_camera_display_title(
            source_type=str(marker.get("source_type") or ""),
            title=str(marker.get("title") or ""),
            city=str(marker.get("city") or ""),
            country=str(marker.get("country") or ""),
            camera_id=marker.get("id"),
        )
        marker["stream_id"] = extract_camera_stream_id(
            source_type=str(marker.get("source_type") or ""),
            title=str(marker.get("title") or ""),
        )
    payload = {
        "markers": markers,
        "count": len(markers),
        "total": total,
        "truncated": total > limit,
    }
    cache.set(cache_key, payload, TTL_CAMERAS)
    logger.info(
        "camera_map_data cache_hit=0 count=%s total=%s truncated=%s elapsed_ms=%.2f",
        payload["count"],
        payload["total"],
        payload["truncated"],
        (time.monotonic() - started) * 1000,
    )
    return payload


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
