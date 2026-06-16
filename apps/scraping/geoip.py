from __future__ import annotations

import hashlib
import ipaddress
import logging
from typing import Any

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.scraping.models import GeoIPCache, GeoLocationProvider

logger = logging.getLogger(__name__)


def _normalize_ip(ip: str) -> str | None:
    try:
        return str(ipaddress.ip_address((ip or "").strip()))
    except ValueError:
        return None


def is_public_ip(ip: str) -> bool:
    normalized = _normalize_ip(ip)
    if not normalized:
        return False
    parsed = ipaddress.ip_address(normalized)
    return parsed.is_global


def public_ip_hash(ips: list[str]) -> str:
    normalized = sorted({_normalize_ip(ip) for ip in ips if _normalize_ip(ip)})
    raw = ",".join(value for value in normalized if value)
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _lookup_cache(ip: str) -> dict[str, Any] | None:
    item = (
        GeoIPCache.objects.filter(provider=GeoLocationProvider.IP_API, ip=ip)
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
            "provider": GeoLocationProvider.IP_API,
            "ip": ip,
            "from_cache": True,
        }

    return {
        "found": True,
        "provider": GeoLocationProvider.IP_API,
        "ip": ip,
        "country": item.country,
        "country_code": item.country_code,
        "region": item.region,
        "city": item.city,
        "latitude": item.latitude,
        "longitude": item.longitude,
        "raw_payload": item.raw_payload,
        "from_cache": True,
    }


def _store_cache(ip: str, result: dict[str, Any]) -> None:
    with transaction.atomic():
        item, _ = GeoIPCache.objects.select_for_update().get_or_create(
            provider=GeoLocationProvider.IP_API,
            ip=ip,
        )
        item.is_hit = bool(result.get("found"))
        item.country = str(result.get("country") or "")
        item.country_code = str(result.get("country_code") or "").upper()[:2]
        item.region = str(result.get("region") or "")
        item.city = str(result.get("city") or "")
        item.latitude = result.get("latitude")
        item.longitude = result.get("longitude")
        item.raw_payload = result.get("raw_payload") or {}
        item.hits += 1
        item.last_used_at = timezone.now()
        item.save()


def geolocate_ip(ip: str, *, force_refresh: bool = False) -> dict[str, Any]:
    normalized_ip = _normalize_ip(ip)
    if not normalized_ip or not is_public_ip(normalized_ip):
        return {
            "found": False,
            "provider": GeoLocationProvider.IP_API,
            "ip": normalized_ip or "",
            "reason": "not_public_ip",
        }

    if not force_refresh:
        cached = _lookup_cache(normalized_ip)
        if cached is not None:
            return cached

    timeout_seconds = float(getattr(settings, "GEOIP_HTTP_TIMEOUT_SECONDS", 4.0))
    result: dict[str, Any] = {
        "found": False,
        "provider": GeoLocationProvider.IP_API,
        "ip": normalized_ip,
        "raw_payload": {},
    }
    try:
        # ip-api free tier does not require an API key and is enough for
        # best-effort geolocation during background sync.
        url = f"http://ip-api.com/json/{normalized_ip}"
        fields = "status,message,country,countryCode,regionName,city,lat,lon,query"
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(url, params={"fields": fields})
            response.raise_for_status()
            payload = response.json()

        if isinstance(payload, dict) and payload.get("status") == "success":
            lat = payload.get("lat")
            lon = payload.get("lon")
            result = {
                "found": True,
                "provider": GeoLocationProvider.IP_API,
                "ip": normalized_ip,
                "country": str(payload.get("country") or ""),
                "country_code": str(payload.get("countryCode") or "").upper()[:2],
                "region": str(payload.get("regionName") or ""),
                "city": str(payload.get("city") or ""),
                "latitude": float(lat) if lat is not None else None,
                "longitude": float(lon) if lon is not None else None,
                "raw_payload": payload,
                "from_cache": False,
            }
        else:
            result["raw_payload"] = payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.warning("GeoIP lookup failed for ip=%s: %s", normalized_ip, exc)

    try:
        _store_cache(normalized_ip, result)
    except Exception as exc:
        logger.warning("GeoIP cache store failed for ip=%s: %s", normalized_ip, exc)
    result.setdefault("from_cache", False)
    return result


def geolocate_public_ips(ips: list[str], *, force_refresh: bool = False) -> dict[str, Any]:
    normalized_ips = sorted(
        {
            normalized
            for normalized in (_normalize_ip(ip) for ip in ips)
            if normalized and is_public_ip(normalized)
        }
    )
    if not normalized_ips:
        return {
            "found": False,
            "provider": GeoLocationProvider.IP_API,
            "public_ips": [],
        }

    attempted: list[dict[str, Any]] = []
    for ip in normalized_ips:
        result = geolocate_ip(ip, force_refresh=force_refresh)
        attempted.append(
            {
                "ip": str(result.get("ip") or ip),
                "found": bool(result.get("found")),
                "from_cache": bool(result.get("from_cache")),
                "country_code": str(result.get("country_code") or ""),
                "country": str(result.get("country") or ""),
                "city": str(result.get("city") or ""),
                "region": str(result.get("region") or ""),
                "reason": str(result.get("reason") or ""),
            }
        )
        if result.get("found"):
            found_payload = dict(result)
            found_payload["public_ips"] = normalized_ips
            found_payload["attempted"] = attempted
            return found_payload

    return {
        "found": False,
        "provider": GeoLocationProvider.IP_API,
        "public_ips": normalized_ips,
        "attempted": attempted,
    }
