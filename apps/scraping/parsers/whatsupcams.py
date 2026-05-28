"""WhatsUpCams scraper.

Data source:
- Streams index: https://services.whatsupcams.com/streams/
- Stream details: https://services.whatsupcams.com/streams/<stream_id>

WhatsUpCams stream payloads do not include exact geocoordinates.
We infer location from stream IDs and optional override maps, then resolve
coordinates through Nominatim with persistent DB caching.
"""
from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache
from typing import Any, AsyncIterator

import httpx
from django.conf import settings
from tenacity import retry, stop_after_attempt, wait_exponential

from apps.cameras.models import SourceType
from apps.scraping.config import get_whatsupcams_country_codes
from apps.scraping.geolocation import resolve_location_candidates
from apps.scraping.http import build_client, get_limiter
from apps.scraping.parsers.whatsupcams_mappings import (
    WUC_STREAM_LOCATION_OVERRIDES,
    WUC_STREAM_PREFIX_OVERRIDES,
)

logger = logging.getLogger(__name__)

STREAMS_BASE_URL = "https://services.whatsupcams.com/streams"
STREAMS_LIST_URL = f"{STREAMS_BASE_URL}/"

STREAMS_LIMITER = get_limiter(max_rate=2, time_period=1)

COUNTRY_NAMES: dict[str, str] = {
    "BA": "Bosnia and Herzegovina",
    "DO": "Dominican Republic",
    "ES": "Spain",
    "GR": "Greece",
    "HR": "Croatia",
    "IE": "Ireland",
    "IT": "Italy",
    "MK": "North Macedonia",
    "NL": "Netherlands",
    "SI": "Slovenia",
}


@lru_cache(maxsize=1)
def _get_effective_mappings() -> tuple[dict[str, str], dict[str, Any]]:
    prefix: dict[str, str] = dict(WUC_STREAM_PREFIX_OVERRIDES)
    location: dict[str, Any] = dict(WUC_STREAM_LOCATION_OVERRIDES)

    cfg_prefix = getattr(settings, "WUC_STREAM_PREFIX_OVERRIDES", {})
    cfg_location = getattr(settings, "WUC_STREAM_LOCATION_OVERRIDES", {})

    if isinstance(cfg_prefix, dict):
        prefix.update({str(k): str(v) for k, v in cfg_prefix.items()})
    if isinstance(cfg_location, dict):
        location.update({str(k): v for k, v in cfg_location.items()})

    return prefix, location


def _location_override_label(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)) and value:
        if len(value) > 1 and isinstance(value[1], str) and value[1].strip():
            return value[1].strip()
        first = value[0]
        if isinstance(first, str):
            return first.strip()
    return ""


def _location_override_search_query(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)) and value:
        first = value[0]
        if isinstance(first, str):
            return first.strip()
    return ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=12))
async def _fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    async with STREAMS_LIMITER:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def _country_code_from_stream_id(stream_id: str) -> str:
    prefix = (stream_id or "").split("_", 1)[0].strip().upper()
    return prefix if len(prefix) == 2 and prefix.isalpha() else ""


def _humanize_slug(value: str) -> str:
    clean = re.sub(r"[\-_]+", " ", value or "").strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean.title()


def _slug_place_from_stream_id(stream_id: str, country_code: str) -> str:
    text = (stream_id or "").strip().lower()
    prefix = f"{country_code.lower()}_" if country_code else ""
    if prefix and text.startswith(prefix):
        text = text[len(prefix) :]
    text = re.sub(r"\d+", "", text)
    return text.strip("_-")


def _extract_stream_url(payload: dict[str, Any]) -> str:
    hls = payload.get("hls") or {}
    if isinstance(hls, dict):
        url = str(hls.get("url") or "").strip()
        if url:
            return url

    rtmp = payload.get("rtmp") or {}
    if isinstance(rtmp, dict):
        uri = str(rtmp.get("uri") or "").strip()
        if uri:
            return uri

    return ""


def _build_location_candidates(
    stream_id: str,
    payload: dict[str, Any],
    *,
    country_code: str,
    country_name: str,
) -> list[str]:
    candidates: list[str] = []
    prefix_overrides, location_overrides = _get_effective_mappings()

    override_value = location_overrides.get(stream_id)
    exact_search_query = _location_override_search_query(override_value)
    exact_label = _location_override_label(override_value)

    # Prefer search-oriented override (usually first tuple value) for geocoding precision.
    if exact_search_query:
        candidates.append(
            f"{exact_search_query}, {country_name}" if country_name else exact_search_query
        )
    # Keep friendly label as secondary geocoding candidate.
    if exact_label and exact_label.lower() != exact_search_query.lower():
        candidates.append(f"{exact_label}, {country_name}" if country_name else exact_label)

    slug_place = _slug_place_from_stream_id(stream_id, country_code)
    prefixed_key = f"{country_code.lower()}_{slug_place}" if country_code else slug_place

    prefix_override = prefix_overrides.get(prefixed_key)
    if prefix_override:
        candidates.append(
            f"{prefix_override}, {country_name}" if country_name else prefix_override
        )

    if slug_place:
        candidates.append(
            f"{_humanize_slug(slug_place)}, {country_name}"
            if country_name
            else _humanize_slug(slug_place)
        )

    pois = payload.get("pois") or []
    if isinstance(pois, list):
        for poi in pois:
            if isinstance(poi, dict):
                poi_name = str(poi.get("name") or poi.get("title") or "").strip()
                if poi_name:
                    candidates.append(
                        f"{poi_name}, {country_name}" if country_name else poi_name
                    )
            elif isinstance(poi, str) and poi.strip():
                candidates.append(f"{poi.strip()}, {country_name}" if country_name else poi.strip())

    tags = payload.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.strip():
                candidates.append(f"{tag.strip()}, {country_name}" if country_name else tag.strip())

    if country_name:
        candidates.append(country_name)

    # Stable de-duplication
    seen: set[str] = set()
    deduped: list[str] = []
    for item in candidates:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item.strip())
    return deduped


def _resolve_camera_title(
    stream_id: str,
    payload: dict[str, Any],
    *,
    country_code: str,
    city: str,
) -> str:
    _, location_overrides = _get_effective_mappings()
    override_label = _location_override_label(location_overrides.get(stream_id))
    if override_label:
        return override_label

    payload_title = str(
        payload.get("title")
        or payload.get("cameraName")
        or payload.get("streamName")
        or payload.get("label")
        or ""
    ).strip()
    if payload_title:
        return payload_title

    payload_name = str(payload.get("name") or "").strip()
    if payload_name and payload_name.lower() != stream_id.lower():
        return payload_name

    slug_place = _slug_place_from_stream_id(stream_id, country_code)
    human_place = _humanize_slug(slug_place) if slug_place else ""

    if city and human_place and city.lower() != human_place.lower():
        return f"{city} - {human_place}"
    if city:
        return city
    if human_place:
        return human_place
    return stream_id


def _city_from_label(label: str) -> str:
    text = (label or "").strip()
    if not text:
        return ""
    # Keep left-most place-like token for labels such as:
    # - "Samobor - Main Square"
    # - "Rijeka, Korzo"
    text = text.split(" - ", 1)[0].strip()
    text = text.split(",", 1)[0].strip()
    return text


def _resolve_city_fallback(stream_id: str, *, country_code: str) -> str:
    _, location_overrides = _get_effective_mappings()
    label = _location_override_label(location_overrides.get(stream_id))
    mapped_city = _city_from_label(label)
    if mapped_city:
        return mapped_city

    slug_place = _slug_place_from_stream_id(stream_id, country_code)
    if slug_place:
        return _humanize_slug(slug_place)
    return ""


def _stream_ids_from_payload(data: Any) -> list[str]:
    if isinstance(data, list):
        return sorted({str(item).strip().lower() for item in data if str(item).strip()})

    if isinstance(data, dict):
        stream_list = data.get("streams")
        if isinstance(stream_list, list):
            return sorted({str(item).strip().lower() for item in stream_list if str(item).strip()})

    return []


async def _build_camera_from_stream(client: httpx.AsyncClient, stream_id: str) -> dict[str, Any]:
    detail_url = f"{STREAMS_BASE_URL}/{stream_id}"
    try:
        payload = await _fetch_json(client, detail_url)
        if not isinstance(payload, dict):
            payload = {}
    except Exception as exc:
        logger.warning("WUC: stream detail fetch failed for %s: %s", stream_id, exc)
        payload = {}

    country_code = _country_code_from_stream_id(stream_id)
    country_name = COUNTRY_NAMES.get(country_code, country_code)
    stream_url = _extract_stream_url(payload)
    preview_image = str(payload.get("snapshot") or "").strip()

    location_candidates = _build_location_candidates(
        stream_id,
        payload,
        country_code=country_code,
        country_name=country_name,
    )
    geocoded = await resolve_location_candidates(
        location_candidates,
        country_code=country_code,
    )

    latitude = geocoded.get("latitude")
    longitude = geocoded.get("longitude")
    city = str(geocoded.get("city") or "").strip()
    if not city:
        city = _resolve_city_fallback(stream_id, country_code=country_code)
    title = _resolve_camera_title(
        stream_id,
        payload,
        country_code=country_code,
        city=city,
    )

    source_payload = {
        "stream_id": stream_id,
        "api_url": detail_url,
        "resolved_title": title,
        "stream_payload": payload,
        "location_candidates": location_candidates,
        "geocoded": {
            "found": geocoded.get("found", False),
            "from_cache": geocoded.get("from_cache", False),
            "query": geocoded.get("query", ""),
            "display_name": geocoded.get("display_name", ""),
        },
    }

    return {
        "source_type": SourceType.WHATSUPCAMS,
        "title": title,
        "page_url": detail_url,
        "preview_image": preview_image,
        "stream_url": stream_url,
        "country": geocoded.get("raw_payload", {}).get("address", {}).get("country", country_name),
        "country_code": country_code,
        "region": geocoded.get("region", ""),
        "city": city,
        "latitude": latitude,
        "longitude": longitude,
        "zip_code": geocoded.get("zip_code", ""),
        "timezone": "",
        "manufacturer": "",
        "has_partial_metadata": not bool(stream_url),
        "source_payload": source_payload,
    }


async def scrape_all(
    resolve_streams: bool = True,
    max_pages: int = 1,
    *,
    target_country_code: str | None = None,
) -> AsyncIterator[dict]:
    """Async generator yielding WhatsUpCams camera dicts.

    Args:
        resolve_streams: Kept for compatibility with existing call sites.
        max_pages: Kept for compatibility with existing call sites.
        target_country_code: Optional ISO country code to scrape only one country.
    """
    _ = resolve_streams
    _ = max_pages

    allowed_country_codes = set(get_whatsupcams_country_codes())
    if target_country_code:
        allowed_country_codes = {target_country_code.strip().upper()}

    async with build_client() as client:
        try:
            listing_payload = await _fetch_json(client, STREAMS_LIST_URL)
        except Exception as exc:
            logger.error("WUC: failed to fetch stream list: %s", exc)
            return

        stream_ids = _stream_ids_from_payload(listing_payload)
        if not stream_ids:
            logger.warning("WUC: stream list was empty")
            return

        stream_ids = [
            stream_id
            for stream_id in stream_ids
            if _country_code_from_stream_id(stream_id) in allowed_country_codes
        ]
        if not stream_ids:
            logger.warning("WUC: no streams matched countries=%s", sorted(allowed_country_codes))
            return

        logger.info(
            "WUC: discovered %d streams after country filter=%s",
            len(stream_ids),
            sorted(allowed_country_codes),
        )

        semaphore = asyncio.Semaphore(8)

        async def _resolve_one(stream_id: str) -> dict[str, Any]:
            async with semaphore:
                return await _build_camera_from_stream(client, stream_id)

        batch_size = 25
        for start in range(0, len(stream_ids), batch_size):
            chunk = stream_ids[start : start + batch_size]
            results = await asyncio.gather(*[_resolve_one(stream_id) for stream_id in chunk], return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("WUC: failed to resolve one stream: %s", result)
                    continue
                yield result
