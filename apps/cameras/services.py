from __future__ import annotations

import logging
import time
import re
import hashlib
import json
from urllib.parse import quote
from typing import Any

import httpx
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.common.cache import TTL_CAMERAS, versioned_key, DOMAIN_CAMERAS
from apps.cameras.models import (
    Camera,
    CameraCheckLog,
    Go2RTCConfigSnapshot,
    Go2RTCInstance,
    Go2RTCStream,
    SourceType,
)

logger = logging.getLogger(__name__)

CAMERA_LOG_RETENTION_DAYS = 30
WUC_STREAM_ID_PREFIXES = ("ba_", "do_", "es_", "gr_", "hr_", "ie_", "it_", "mk_", "nl_", "si_")
GO2RTC_READ_ONLY_METHODS = {"GET"}


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
        stream_slug = raw_title.split("_", 1)[1] if "_" in raw_title else raw_title
        stream_slug = re.sub(r"\d+", "", stream_slug).strip("_- ")
        derived_place = re.sub(r"[_\-]+", " ", stream_slug).strip().title() if stream_slug else ""

        if raw_city and raw_country:
            return f"{raw_city}, {raw_country}"
        if raw_city:
            return raw_city
        if derived_place and raw_country:
            return f"{derived_place}, {raw_country}"
        if derived_place:
            return derived_place
        if raw_country:
            return raw_country

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
    
    # Strict live-only for Windy: exclude partial metadata cameras
    if source_type == SourceType.WINDY:
        qs = qs.filter(has_partial_metadata=False)

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
    
    Windy strict mode:
    - Reject (do not insert/update) any Windy camera without stream_url.
    - Returns (None, False) if rejected.
    """
    source_type = data.get("source_type")
    page_url = data.get("page_url", "")
    stream_url = data.get("stream_url", "").strip()
    
    # STRICT LIVE-ONLY for Windy: reject non-live cameras
    if source_type == SourceType.WINDY and not stream_url:
        logger.warning(
            "WINDY: Rejecting camera (no stream_url) page_url=%s",
            page_url,
        )
        return None, False

    # Never let the scraper overwrite is_online on existing cameras.
    defaults = {
        k: v
        for k, v in data.items()
        if k not in ("source_type", "page_url", "is_online")
    }

    with transaction.atomic():
        queryset = (
            Camera.objects.select_for_update()
            .filter(source_type=source_type, page_url=page_url)
            .order_by("-updated_at", "-id")
        )

        camera = queryset.first()
        created = camera is None

        if created:
            camera = Camera.objects.create(
                source_type=source_type,
                page_url=page_url,
                **defaults,
            )
            # Presume online when we have a direct stream URL.
            camera.is_online = bool(data.get("stream_url", "").strip())
            camera.save(update_fields=["is_online", "updated_at"])
        else:
            updated_fields: list[str] = []
            for key, value in defaults.items():
                if getattr(camera, key) != value:
                    setattr(camera, key, value)
                    updated_fields.append(key)
            if updated_fields:
                updated_fields.append("updated_at")
                camera.save(update_fields=updated_fields)

            duplicate_ids = list(queryset.values_list("id", flat=True)[1:])
            if duplicate_ids:
                logger.warning(
                    "Found duplicate cameras for source_type=%s page_url=%s duplicates=%s; deactivating duplicates",
                    source_type,
                    page_url,
                    duplicate_ids,
                )
                Camera.objects.filter(id__in=duplicate_ids).update(is_active=False)
    return camera, created


def normalize_go2rtc_base_url(raw_url: str | None = None) -> str:
    base_url = (raw_url or settings.GO2RTC_BASE_URL or "").strip()
    return base_url.rstrip("/")


def _stable_json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _config_hash(payload: dict[str, Any]) -> str:
    raw = _stable_json_dumps(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _config_diff_summary(old: Any, new: Any) -> dict[str, Any]:
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []

    def walk(old_value: Any, new_value: Any, path: str) -> None:
        if type(old_value) is not type(new_value):
            changed.append(path or "<root>")
            return

        if isinstance(old_value, dict):
            old_keys = set(old_value.keys())
            new_keys = set(new_value.keys())
            for key in sorted(new_keys - old_keys):
                added.append(f"{path}.{key}" if path else str(key))
            for key in sorted(old_keys - new_keys):
                removed.append(f"{path}.{key}" if path else str(key))
            for key in sorted(old_keys & new_keys):
                next_path = f"{path}.{key}" if path else str(key)
                walk(old_value[key], new_value[key], next_path)
            return

        if isinstance(old_value, list):
            if len(old_value) != len(new_value):
                changed.append(path or "<root>")
                return
            for idx, (old_item, new_item) in enumerate(zip(old_value, new_value)):
                walk(old_item, new_item, f"{path}[{idx}]" if path else f"[{idx}]")
            return

        if old_value != new_value:
            changed.append(path or "<root>")

    walk(old, new, "")
    max_sample = 50
    return {
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "added_paths": added[:max_sample],
        "removed_paths": removed[:max_sample],
        "changed_paths": changed[:max_sample],
    }


def _short_repr(value: Any, max_len: int = 240) -> str:
    text = _stable_json_dumps(value)
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}…"


def build_config_diff_rows(old: Any, new: Any, *, max_rows: int = 500) -> list[dict[str, str]]:
    """Build detailed row-level diff between two config payloads.

    Returns rows with keys: path, change_type, before, after.
    """
    rows: list[dict[str, str]] = []

    def add_row(path: str, change_type: str, before: Any, after: Any) -> None:
        if len(rows) >= max_rows:
            return
        rows.append(
            {
                "path": path or "<root>",
                "change_type": change_type,
                "before": _short_repr(before),
                "after": _short_repr(after),
            }
        )

    def walk(old_value: Any, new_value: Any, path: str) -> None:
        if len(rows) >= max_rows:
            return

        if type(old_value) is not type(new_value):
            add_row(path, "changed", old_value, new_value)
            return

        if isinstance(old_value, dict):
            old_keys = set(old_value.keys())
            new_keys = set(new_value.keys())

            for key in sorted(new_keys - old_keys):
                next_path = f"{path}.{key}" if path else str(key)
                add_row(next_path, "added", None, new_value[key])
            for key in sorted(old_keys - new_keys):
                next_path = f"{path}.{key}" if path else str(key)
                add_row(next_path, "removed", old_value[key], None)

            for key in sorted(old_keys & new_keys):
                next_path = f"{path}.{key}" if path else str(key)
                walk(old_value[key], new_value[key], next_path)
            return

        if isinstance(old_value, list):
            if len(old_value) != len(new_value):
                add_row(path, "changed", old_value, new_value)
            for idx, (old_item, new_item) in enumerate(zip(old_value, new_value)):
                next_path = f"{path}[{idx}]" if path else f"[{idx}]"
                walk(old_item, new_item, next_path)
            if len(new_value) > len(old_value):
                for idx in range(len(old_value), len(new_value)):
                    next_path = f"{path}[{idx}]" if path else f"[{idx}]"
                    add_row(next_path, "added", None, new_value[idx])
            elif len(old_value) > len(new_value):
                for idx in range(len(new_value), len(old_value)):
                    next_path = f"{path}[{idx}]" if path else f"[{idx}]"
                    add_row(next_path, "removed", old_value[idx], None)
            return

        if old_value != new_value:
            add_row(path, "changed", old_value, new_value)

    walk(old, new, "")
    return rows


def fetch_go2rtc_instance_payloads(
    *,
    base_url: str,
    timeout_seconds: float = 5.0,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """Fetch streams and config payloads from a go2rtc instance.

    Returns (streams, config, error_message).
    """
    normalized_base = normalize_go2rtc_base_url(base_url)
    if not normalized_base:
        return [], {}, "go2rtc base URL is empty."

    streams_url = f"{normalized_base}/api/streams"
    config_url = f"{normalized_base}/api/config"

    def _readonly_get(client: httpx.Client, url: str) -> httpx.Response:
        method = "GET"
        if method not in GO2RTC_READ_ONLY_METHODS:
            raise ValueError("go2rtc manager is read-only for remote configuration")
        return client.get(url)

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            streams_resp = _readonly_get(client, streams_url)
            streams_resp.raise_for_status()
            streams_payload = streams_resp.json()

            config_resp = _readonly_get(client, config_url)
            config_resp.raise_for_status()
            config_payload = config_resp.json()
    except Exception as exc:
        logger.warning("go2rtc manager sync failed base_url=%s error=%s", normalized_base, exc)
        return [], {}, f"Unable to fetch go2rtc data from {normalized_base}."

    streams_obj: dict[str, Any]
    if isinstance(streams_payload, dict) and isinstance(streams_payload.get("streams"), dict):
        streams_obj = streams_payload["streams"]
    elif isinstance(streams_payload, dict):
        streams_obj = streams_payload
    else:
        streams_obj = {}

    items: list[dict[str, Any]] = []
    for stream_name, stream_data in streams_obj.items():
        if not isinstance(stream_name, str) or not stream_name.strip():
            continue
        row_payload = stream_data if isinstance(stream_data, dict) else {}
        items.append(
            {
                "stream_name": stream_name.strip(),
                "producers_count": len(row_payload.get("producers") or []),
                "consumers_count": len(row_payload.get("consumers") or []),
                "stream_payload": row_payload,
            }
        )

    items.sort(key=lambda row: row["stream_name"].lower())
    return items, (config_payload if isinstance(config_payload, dict) else {}), None


def sync_go2rtc_instance(instance: Go2RTCInstance) -> tuple[int, str | None]:
    """Sync one go2rtc instance and persist stream/config snapshots.

    Returns (stream_count, error_message).
    """
    streams, config_payload, error = fetch_go2rtc_instance_payloads(base_url=instance.base_url)
    now = timezone.now()

    if error:
        instance.last_sync_status = Go2RTCInstance.LastSyncStatus.FAILED
        instance.last_sync_error = error
        instance.last_synced_at = now
        instance.save(update_fields=["last_sync_status", "last_sync_error", "last_synced_at", "updated_at"])
        return 0, error

    with transaction.atomic():
        previous_snapshot = instance.config_snapshots.order_by("-fetched_at").first()
        existing = {
            row.stream_name: row
            for row in Go2RTCStream.objects.select_for_update().filter(instance=instance)
        }

        touched_names: set[str] = set()
        to_create: list[Go2RTCStream] = []
        to_update: list[Go2RTCStream] = []

        for row in streams:
            name = row["stream_name"]
            touched_names.add(name)
            if name in existing:
                item = existing[name]
                item.producers_count = int(row["producers_count"])
                item.consumers_count = int(row["consumers_count"])
                item.stream_payload = row["stream_payload"]
                to_update.append(item)
            else:
                to_create.append(
                    Go2RTCStream(
                        instance=instance,
                        stream_name=name,
                        producers_count=int(row["producers_count"]),
                        consumers_count=int(row["consumers_count"]),
                        stream_payload=row["stream_payload"],
                    )
                )

        stale_ids = [row.id for name, row in existing.items() if name not in touched_names]

        if to_create:
            Go2RTCStream.objects.bulk_create(to_create, batch_size=500)
        if to_update:
            Go2RTCStream.objects.bulk_update(
                to_update,
                fields=["producers_count", "consumers_count", "stream_payload", "last_seen_at"],
                batch_size=500,
            )
        if stale_ids:
            Go2RTCStream.objects.filter(id__in=stale_ids).delete()

        new_hash = _config_hash(config_payload)
        is_changed = False
        change_summary: dict[str, Any] = {
            "added_count": 0,
            "removed_count": 0,
            "changed_count": 0,
            "added_paths": [],
            "removed_paths": [],
            "changed_paths": [],
        }

        if previous_snapshot and previous_snapshot.config_hash:
            if previous_snapshot.config_hash != new_hash:
                is_changed = True
                change_summary = _config_diff_summary(previous_snapshot.config_payload or {}, config_payload)

        Go2RTCConfigSnapshot.objects.create(
            instance=instance,
            config_payload=config_payload,
            config_hash=new_hash,
            is_changed=is_changed,
            change_summary=change_summary,
        )

    instance.last_sync_status = Go2RTCInstance.LastSyncStatus.SUCCESS
    instance.last_sync_error = ""
    instance.last_synced_at = now
    instance.save(update_fields=["last_sync_status", "last_sync_error", "last_synced_at", "updated_at"])
    return len(streams), None


def build_go2rtc_stream_urls(base_url: str, stream_name: str) -> dict[str, str]:
    """Build all available go2rtc streaming URLs for a stream.
    
    Supports WebRTC, MSE, HLS, MJPEG in order of preference for web/mobile.
    """
    encoded = quote(stream_name.strip(), safe="")
    return {
        "viewer": f"{base_url}/stream.html?src={encoded}&mode=webrtc&background=false&width=100%25&height=100%25",
        "webrtc_embed": f"{base_url}/webrtc.html?src={encoded}",
        "webrtc": f"{base_url}/api/stream.webrtc?src={encoded}",
        "mse": f"{base_url}/api/stream.mse?src={encoded}",
        "hls": f"{base_url}/api/stream.m3u8?src={encoded}",
        "mjpeg": f"{base_url}/api/stream.mjpeg?src={encoded}",
        "mp4": f"{base_url}/api/stream.mp4?src={encoded}",
    }


def ensure_go2rtc_camera_stream_urls(camera: Camera) -> Camera:
    """Ensure persisted GO2RTC cameras have full URL set and WebRTC player URL as primary."""
    if camera.source_type != SourceType.GO2RTC:
        return camera

    payload = dict(camera.source_payload or {})
    base_url = normalize_go2rtc_base_url(payload.get("base_url") or None)
    stream_name = str(payload.get("stream_name") or "").strip()

    if not stream_name:
        title = (camera.title or "").strip()
        if title:
            stream_name = title

    if not base_url or not stream_name:
        return camera

    urls = build_go2rtc_stream_urls(base_url, stream_name)
    stream_urls = payload.get("stream_urls") if isinstance(payload.get("stream_urls"), dict) else {}
    merged_urls = {**stream_urls, **urls}
    desired_stream_url = urls["webrtc_embed"]

    changed_fields: list[str] = []
    if payload.get("stream_urls") != merged_urls:
        payload["stream_urls"] = merged_urls
        payload.setdefault("provider", "go2rtc")
        payload["base_url"] = base_url
        payload["stream_name"] = stream_name
        camera.source_payload = payload
        changed_fields.append("source_payload")

    if (camera.stream_url or "") != desired_stream_url:
        camera.stream_url = desired_stream_url
        changed_fields.append("stream_url")

    if (camera.page_url or "") != desired_stream_url:
        camera.page_url = desired_stream_url
        changed_fields.append("page_url")

    if changed_fields:
        changed_fields.append("updated_at")
        camera.save(update_fields=changed_fields)

    return camera


def fetch_go2rtc_streams(*, base_url: str | None = None, timeout_seconds: float = 4.0) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch available stream names from go2rtc API.

    Returns (streams, error_message). Stream items include keys:
    - name: stream identifier
    - producers: int
    - consumers: int
    """
    normalized_base = normalize_go2rtc_base_url(base_url)
    if not normalized_base:
        return [], "GO2RTC_BASE_URL is not configured."

    api_url = f"{normalized_base}/api/streams"
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(api_url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("go2rtc stream discovery failed url=%s error=%s", api_url, exc)
        return [], f"Unable to fetch the stream list from: {api_url}"

    streams_obj: dict[str, Any]
    if isinstance(payload, dict) and isinstance(payload.get("streams"), dict):
        streams_obj = payload["streams"]
    elif isinstance(payload, dict):
        streams_obj = payload
    else:
        streams_obj = {}

    items: list[dict[str, Any]] = []
    for stream_name, stream_data in streams_obj.items():
        if not isinstance(stream_name, str) or not stream_name.strip():
            continue
        stream_info = stream_data if isinstance(stream_data, dict) else {}
        producers = len(stream_info.get("producers") or [])
        consumers = len(stream_info.get("consumers") or [])
        items.append(
            {
                "name": stream_name.strip(),
                "producers": producers,
                "consumers": consumers,
            }
        )

    items.sort(key=lambda row: row["name"].lower())
    return items, None


def upsert_go2rtc_camera(*, stream_name: str, title: str = "", base_url: str | None = None) -> tuple[Camera, bool]:
    normalized_base = normalize_go2rtc_base_url(base_url)
    clean_stream_name = stream_name.strip()
    clean_title = title.strip() or clean_stream_name
    
    # Build all streaming URLs; use go2rtc WebRTC player page as primary playback URL
    urls = build_go2rtc_stream_urls(normalized_base, clean_stream_name)
    stream_url = urls["webrtc_embed"]

    data: dict[str, Any] = {
        "source_type": SourceType.GO2RTC,
        "title": clean_title,
        "country": "",
        "country_code": "",
        "city": "",
        "region": "",
        "zip_code": "",
        "timezone": "",
        "manufacturer": "",
        "stream_url": stream_url,
        "preview_image": "",
        "page_url": stream_url,
        "is_active": True,
        "has_partial_metadata": False,
        "source_payload": {
            "provider": "go2rtc",
            "base_url": normalized_base,
            "stream_name": clean_stream_name,
            "stream_urls": urls,
        },
    }
    return upsert_camera(data)
