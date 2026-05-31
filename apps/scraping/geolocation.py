from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.scraping.http import build_client, get_limiter
from apps.scraping.models import GeoLocationCache, GeoLocationProvider

logger = logging.getLogger(__name__)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_LIMITER = get_limiter(max_rate=1, time_period=1)
_GEO_LOCKS: dict[str, asyncio.Lock] = {}


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def _extract_city(address: dict[str, Any]) -> str:
    for key in (
        "city",
        "town",
        "village",
        "municipality",
        "hamlet",
        "suburb",
        "city_district",
        "island",
    ):
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _lookup_cache(normalized_query: str, country_code: str) -> dict[str, Any] | None:
    item = (
        GeoLocationCache.objects.filter(
            provider=GeoLocationProvider.NOMINATIM,
            normalized_query=normalized_query,
            country_code=country_code,
        )
        .order_by("-updated_at")
        .first()
    )
    if item is None:
        return None

    item.hits += 1
    item.last_used_at = timezone.now()
    item.save(update_fields=["hits", "last_used_at", "updated_at"])

    if not item.is_hit:
        return {
            "found": False,
            "from_cache": True,
            "query": item.query,
            "country_code": item.country_code,
        }

    return {
        "found": True,
        "from_cache": True,
        "query": item.query,
        "country_code": item.country_code,
        "latitude": item.latitude,
        "longitude": item.longitude,
        "display_name": item.display_name,
        "city": item.city,
        "region": item.region,
        "zip_code": item.zip_code,
        "raw_payload": item.raw_payload,
    }


def _store_cache(
    *,
    query: str,
    normalized_query: str,
    country_code: str,
    result: dict[str, Any],
) -> None:
    with transaction.atomic():
        item, _ = GeoLocationCache.objects.select_for_update().get_or_create(
            provider=GeoLocationProvider.NOMINATIM,
            normalized_query=normalized_query,
            country_code=country_code,
            defaults={
                "query": query,
            },
        )

        item.query = query
        item.is_hit = bool(result.get("found"))
        item.latitude = result.get("latitude")
        item.longitude = result.get("longitude")
        item.display_name = result.get("display_name", "")
        item.city = result.get("city", "")
        item.region = result.get("region", "")
        item.zip_code = result.get("zip_code", "")
        item.raw_payload = result.get("raw_payload", {})
        item.hits += 1
        item.last_used_at = timezone.now()
        item.save()


async def geocode_query(query: str, *, country_code: str = "") -> dict[str, Any]:
    clean_query = (query or "").strip()
    normalized_query = _normalize_query(clean_query)
    normalized_country = (country_code or "").strip().upper()
    if not normalized_query:
        return {"found": False, "query": clean_query, "country_code": normalized_country}

    cached = await sync_to_async(_lookup_cache, thread_sensitive=True)(
        normalized_query,
        normalized_country,
    )
    if cached is not None:
        return cached

    lock_key = f"{normalized_country}:{normalized_query}"
    lock = _GEO_LOCKS.setdefault(lock_key, asyncio.Lock())
    async with lock:
        # Double-check cache in case another coroutine populated it while waiting.
        cached_after_wait = await sync_to_async(_lookup_cache, thread_sensitive=True)(
            normalized_query,
            normalized_country,
        )
        if cached_after_wait is not None:
            return cached_after_wait

        nominatim_user_agent = getattr(settings, "NOMINATIM_USER_AGENT", "reconeye/1.0")
        headers = {
            "User-Agent": nominatim_user_agent,
            "Accept-Language": "en",
        }
        params = {
            "q": clean_query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
        }
        if normalized_country:
            params["countrycodes"] = normalized_country.lower()

        result: dict[str, Any] = {
            "found": False,
            "query": clean_query,
            "country_code": normalized_country,
            "raw_payload": {},
        }

        try:
            async with NOMINATIM_LIMITER:
                async with build_client(headers=headers, http2=False) as client:
                    response = await client.get(NOMINATIM_SEARCH_URL, params=params)
                    response.raise_for_status()
                    payload = response.json()

            if isinstance(payload, list) and payload:
                first = payload[0] or {}
                address = first.get("address") or {}
                lat = first.get("lat")
                lon = first.get("lon")
                result = {
                    "found": True,
                    "query": clean_query,
                    "country_code": normalized_country,
                    "latitude": float(lat) if lat is not None else None,
                    "longitude": float(lon) if lon is not None else None,
                    "display_name": str(first.get("display_name") or ""),
                    "city": _extract_city(address),
                    "region": str(
                        address.get("state")
                        or address.get("region")
                        or address.get("county")
                        or ""
                    ),
                    "zip_code": str(address.get("postcode") or ""),
                    "raw_payload": first,
                    "from_cache": False,
                }
        except Exception as exc:
            logger.warning("Nominatim geocode failed for query=%r country=%s: %s", clean_query, normalized_country, exc)

        await sync_to_async(_store_cache, thread_sensitive=True)(
            query=clean_query,
            normalized_query=normalized_query,
            country_code=normalized_country,
            result=result,
        )

        result.setdefault("from_cache", False)
        return result


async def resolve_location_candidates(
    candidates: list[str],
    *,
    country_code: str = "",
) -> dict[str, Any]:
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_query(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)

        geocoded = await geocode_query(candidate, country_code=country_code)
        if geocoded.get("found"):
            return geocoded

    return {
        "found": False,
        "country_code": (country_code or "").strip().upper(),
    }
