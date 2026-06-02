"""Windy Webcams API scraper.

API docs: https://api.windy.com/webcams/docs
Authentication header: x-windy-api-key
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any, AsyncIterator
from urllib.parse import urljoin

import httpx
from django.conf import settings
from tenacity import retry, stop_after_attempt, wait_exponential

from apps.cameras.models import SourceType
from apps.scraping.http import build_client, get_limiter

logger = logging.getLogger(__name__)

WINDY_LIMITER = get_limiter(max_rate=3, time_period=1)
M3U8_URL_RE = re.compile(r"https?://[^\s\"'<>]+\.m3u8(?:\?[^\s\"'<>]*)?", re.IGNORECASE)
IFRAME_SRC_RE = re.compile(r"<iframe[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)


def _is_likely_player_page_url(url: str) -> bool:
    text = (url or "").strip().lower()
    return any(
        hint in text
        for hint in (
            "player.php",
            "/player",
            "embed",
            ".html",
            ".htm",
        )
    )


def _is_likely_direct_stream_url(url: str) -> bool:
    text = (url or "").strip().lower()
    return any(
        hint in text
        for hint in (
            ".m3u8",
            ".mjpeg",
            ".mjpg",
            "axis-cgi",
            "video.cgi",
            "/videostream",
            "/streams/",
            "rtsp://",
        )
    )


def _api_base() -> str:
    return str(getattr(settings, "WINDY_API_BASE_URL", "https://api.windy.com") or "https://api.windy.com").rstrip("/")


def _api_key() -> str:
    return str(getattr(settings, "WINDY_API_KEY", "") or "").strip()


def _endpoint() -> str:
    return f"{_api_base()}/webcams/api/v3/webcams"


def _webcam_detail_endpoint(webcam_id: str) -> str:
    return f"{_api_base()}/webcams/api/v3/webcams/{webcam_id}"


def _headers() -> dict[str, str]:
    key = _api_key()
    if not key:
        raise RuntimeError("WINDY_API_KEY is not configured.")
    return {"x-windy-api-key": key}


def _deep_get(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    direct_candidates = [
        payload.get("webcams"),
        payload.get("items"),
        payload.get("results"),
        _deep_get(payload, "result", "webcams"),
        _deep_get(payload, "result", "items"),
        _deep_get(payload, "data", "webcams"),
        payload.get("data"),
    ]
    for candidate in direct_candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]

    # Last-resort: first list of dicts in top-level payload
    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return [item for item in value if isinstance(item, dict)]

    return []


def _extract_detail_item(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        candidate_payloads = [
            payload,
            payload.get("webcam"),
            _deep_get(payload, "result", "webcam"),
            _deep_get(payload, "data", "webcam"),
            payload.get("data"),
            _deep_get(payload, "result", "data"),
        ]
        for candidate in candidate_payloads:
            if isinstance(candidate, dict) and (
                candidate.get("id") or candidate.get("webcamId") or candidate.get("webcam_id")
            ):
                return candidate
    return None


def _item_webcam_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("webcamId") or item.get("webcam_id") or "").strip()


def _item_country_code(item: dict[str, Any]) -> str:
    return str(
        _deep_get(item, "location", "country", "code")
        or _deep_get(item, "location", "country_code")
        or item.get("countryCode")
        or ""
    ).strip().upper()


def _extract_stream_url(item: dict[str, Any]) -> str:
    candidates = [
        _deep_get(item, "player", "live"),
        _deep_get(item, "player", "live", "url"),
        _deep_get(item, "player", "url"),
        _deep_get(item, "stream", "url"),
        _deep_get(item, "live", "url"),
        item.get("streamUrl"),
        item.get("videoUrl"),
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_preview(item: dict[str, Any]) -> str:
    candidates = [
        _deep_get(item, "images", "current", "preview"),
        _deep_get(item, "images", "current", "thumbnail"),
        _deep_get(item, "image", "current", "preview"),
        _deep_get(item, "player", "day", "thumbnail"),
        _deep_get(item, "player", "thumbnail"),
        item.get("preview"),
        item.get("image"),
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_m3u8_url(text: str) -> str:
    match = M3U8_URL_RE.search(text)
    if not match:
        return ""
    return html.unescape(match.group(0).replace("\\/", "/")).strip()


def _extract_iframe_src(text: str) -> str:
    match = IFRAME_SRC_RE.search(text)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def _extract_js_var(text: str, name: str) -> str:
    pattern = re.compile(rf"var\s+{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]\s*;", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def _build_ipcamlive_m3u8(text: str) -> str:
    address = _extract_js_var(text, "address")
    stream_id = _extract_js_var(text, "streamid")
    if not address or not stream_id:
        return ""
    # Prefer HTTPS for browser mixed-content safety.
    if address.startswith("http://"):
        address = "https://" + address[len("http://") :]
    return f"{address.rstrip('/')}/streams/{stream_id}/master.m3u8"


async def _is_valid_m3u8_url(client: httpx.AsyncClient, url: str) -> bool:
    """Best-effort HLS manifest validation.

    Some IPCamLive cameras expose address+streamid variables even when the
    generated manifest URL is unavailable (404). We validate the URL before
    returning it to avoid rendering a broken HLS player.
    """
    if not url or ".m3u8" not in url.lower():
        return False
    try:
        async with WINDY_LIMITER:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,text/plain,*/*",
                    "Referer": "https://ipcamlive.com/",
                },
            )
        if response.status_code != 200:
            return False
        body_head = (response.text or "")[:1024]
        return "#EXTM3U" in body_head
    except Exception:
        return False


async def _fetch_webcam_detail(client: httpx.AsyncClient, webcam_id: str) -> dict[str, Any]:
    async with WINDY_LIMITER:
        response = await client.get(_webcam_detail_endpoint(webcam_id), headers=_headers())
    response.raise_for_status()
    payload = response.json()
    detail = _extract_detail_item(payload)
    if detail is not None:
        return detail
    if isinstance(payload, dict):
        return payload
    return {}


async def _coerce_windy_camera(item: dict[str, Any], client: httpx.AsyncClient) -> dict[str, Any] | None:
    camera = _camera_from_item(item)
    if camera is not None:
        return camera

    webcam_id = _item_webcam_id(item)
    if not webcam_id:
        return None

    try:
        detail_item = await _fetch_webcam_detail(client, webcam_id)
    except Exception as exc:
        logger.debug("WINDY: failed to fetch webcam detail for %s: %s", webcam_id, exc)
        return None

    return _camera_from_item(detail_item)


def _pages_until_offset_limit(start_page: int, max_pages: int, per_page: int) -> int:
    start_offset = max(0, start_page) * per_page
    if start_offset > 1000:
        return 0
    remaining_items = 1000 - start_offset
    return min(max_pages, (remaining_items // per_page) + 1)


async def _resolve_direct_stream_url(client: httpx.AsyncClient, webcam_id: str) -> str:
    """Resolve direct playable stream URL for a Windy webcam.

    Strategy:
    1) Fetch Windy stream page (/webcams/stream/{id})
    2) Try to extract direct .m3u8 from page
    3) Follow iframe src and extract .m3u8 (or IPCamLive address+streamid)
    """
    stream_page_url = f"https://webcams.windy.com/webcams/stream/{webcam_id}"

    try:
        async with WINDY_LIMITER:
            page_response = await client.get(stream_page_url)
        page_response.raise_for_status()
    except Exception as exc:
        logger.debug("WINDY: failed to fetch stream page for %s: %s", webcam_id, exc)
        return ""

    page_text = page_response.text or ""

    direct_m3u8 = _extract_m3u8_url(page_text)
    if direct_m3u8:
        return direct_m3u8

    iframe_src = _extract_iframe_src(page_text)
    if not iframe_src:
        return ""

    if iframe_src.startswith("//"):
        iframe_src = f"https:{iframe_src}"
    elif not iframe_src.startswith(("http://", "https://")):
        iframe_src = urljoin(stream_page_url, iframe_src)

    iframe_direct_m3u8 = _extract_m3u8_url(iframe_src)
    if iframe_direct_m3u8:
        return iframe_direct_m3u8

    # Some Windy stream pages point iframe directly to MJPEG/HLS/RTSP endpoints.
    # Do NOT fetch these URLs here because they can be long-lived streaming responses
    # that make scraping appear stuck. Persist direct URL as-is.
    if _is_likely_direct_stream_url(iframe_src) and not _is_likely_player_page_url(iframe_src):
        return iframe_src

    # If URL does not look like HTML player page, avoid costly fetch and keep direct URL.
    if not _is_likely_player_page_url(iframe_src):
        return iframe_src

    try:
        async with WINDY_LIMITER:
            iframe_response = await client.get(
                iframe_src,
                headers={"User-Agent": "Mozilla/5.0"},
            )
        iframe_response.raise_for_status()
    except Exception as exc:
        logger.debug("WINDY: failed to fetch iframe page for %s: %s", webcam_id, exc)
        return ""

    iframe_text = iframe_response.text or ""

    nested_m3u8 = _extract_m3u8_url(iframe_text)
    if nested_m3u8 and await _is_valid_m3u8_url(client, nested_m3u8):
        return nested_m3u8

    ipcamlive_m3u8 = _build_ipcamlive_m3u8(iframe_text)
    if ipcamlive_m3u8 and await _is_valid_m3u8_url(client, ipcamlive_m3u8):
        return ipcamlive_m3u8

    # Fallback to provider's own player page if direct HLS URL is unavailable.
    # This avoids showing a broken HLS player for cameras with stale/unavailable
    # generated manifests.
    return iframe_src


def _camera_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a Windy webcam item into Camera fields.
    
    Returns None if camera has no live stream (player.live),
    implementing strict live-only filtering at parse time.
    """
    webcam_id = str(item.get("id") or item.get("webcamId") or item.get("webcam_id") or "").strip()
    title = str(item.get("title") or item.get("name") or item.get("webcam") or webcam_id or "Windy camera").strip()

    latitude = _deep_get(item, "location", "latitude")
    longitude = _deep_get(item, "location", "longitude")
    if latitude is None:
        latitude = item.get("latitude")
    if longitude is None:
        longitude = item.get("longitude")

    country = (
        str(_deep_get(item, "location", "country", "name") or "").strip()
        or str(_deep_get(item, "location", "country") or "").strip()
    )
    country_code = str(
        _deep_get(item, "location", "country", "code")
        or _deep_get(item, "location", "country_code")
        or item.get("countryCode")
        or ""
    ).strip().upper()
    region = str(_deep_get(item, "location", "region") or item.get("region") or "").strip()
    city = str(_deep_get(item, "location", "city") or item.get("city") or "").strip()
    timezone = str(_deep_get(item, "location", "timezone") or item.get("timezone") or "").strip()

    player_live = str(_deep_get(item, "player", "live") or "").strip()
    player_day = str(_deep_get(item, "player", "day") or "").strip()
    
    # STRICT LIVE-ONLY: Skip any camera without player.live URL
    if not player_live:
        logger.debug(
            "WINDY: Skipping camera %s (no player.live; only preview available)",
            webcam_id,
        )
        return None
    
    # Default stream URL fallback (HTML page with embedded player).
    # During scrape loop we attempt to resolve direct .m3u8 URL and override this.
    stream_url = f"https://webcams.windy.com/webcams/stream/{webcam_id}"
    preview_image = _extract_preview(item)

    # Page URL: Link to Windy's main webcam page (for context & sharing)
    page_url = f"https://www.windy.com/webcams/{webcam_id}"

    source_payload = {
        "provider": "windy",
        "webcam_id": webcam_id,
        "player_live": player_live,
        "player_day": player_day,
        "raw": item,
    }

    return {
        "source_type": SourceType.WINDY,
        "title": title,
        "page_url": page_url,
        "preview_image": preview_image,
        "stream_url": stream_url,
        "country": country,
        "country_code": country_code,
        "region": region,
        "city": city,
        "latitude": latitude,
        "longitude": longitude,
        "zip_code": "",
        "timezone": timezone,
        "manufacturer": "",
        "has_partial_metadata": False,  # Live cameras are always fully qualified
        "source_payload": source_payload,
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=12), reraise=True)
async def _fetch_webcams_page(client: httpx.AsyncClient, *, limit: int, offset: int, country_code: str | None = None) -> Any:
    params: dict[str, Any] = {
        "limit": max(1, min(50, int(limit))),
        "offset": max(0, int(offset)),
        "include": "location,images,player",
    }
    if country_code:
        params["country"] = country_code.strip().upper()

    async with WINDY_LIMITER:
        response = await client.get(_endpoint(), params=params, headers=_headers())
        if response.status_code >= 400:
            logger.warning(
                "WINDY API error status=%s params=%s body=%s",
                response.status_code,
                params,
                response.text[:300],
            )
        response.raise_for_status()
        return response.json()


async def scrape_all(
    *,
    target_country_code: str | None = None,
    max_pages: int = 20,
    start_page: int = 0,
) -> AsyncIterator[dict[str, Any]]:
    per_page = int(getattr(settings, "WINDY_WEB_CAMS_PER_PAGE", 100) or 100)
    per_page = max(1, min(50, per_page))
    yielded_count = 0

    async with build_client() as client:
        api_pages = _pages_until_offset_limit(start_page=start_page, max_pages=max_pages, per_page=per_page)

        # Phase 1: use the regular /webcams endpoint while we're still under the
        # API tier offset limit (<= 1000). This keeps the first 1000 items fast.
        for page_offset in range(api_pages):
            page = start_page + page_offset
            offset = page * per_page
            try:
                payload = await _fetch_webcams_page(
                    client,
                    limit=per_page,
                    offset=offset,
                    country_code=(target_country_code or None),
                )
            except httpx.HTTPStatusError as exc:
                # Windy API returns 400 for offset > 1000 even though we calculated
                # offset based on page 20, per_page 50 (offset = page * 50).
                # When this happens, stop pagination and return what we have.
                if exc.response.status_code == 400:
                    logger.warning(
                        f"WINDY: hit Windy offset limit at page {page} (offset={offset}); "
                        f"returning {yielded_count} cameras collected so far"
                    )
                    return
                raise

            items = _extract_items(payload)
            if not items:
                if page == 0:
                    logger.warning("WINDY: empty payload on first page")
                break

            for item in items:
                try:
                    cam = await _coerce_windy_camera(item, client)
                    if cam is None or not cam.get("page_url"):
                        continue
                    yielded_count += 1
                    yield cam
                except Exception as exc:
                    logger.warning("WINDY: failed to parse webcam item: %s", exc)

            if len(items) < per_page:
                return

        # Phase 2: for offsets above the Windy tier cap, we would normally use the
        # full export file, but Windy's /webcams/export/all-webcams.json endpoint
        # returns 403 Forbidden (access denied). Skip Phase 2 and return what we have.
        logger.info(
            "WINDY: Phase 1 complete with %s pages and %s cameras; "
            "skipping export fallback (403 access denied)",
            api_pages,
            yielded_count,
        )
        return


async def collect_webcams(
    *,
    target_country_code: str | None = None,
    max_pages: int = 20,
    start_page: int = 0,
) -> list[dict[str, Any]]:
    """Collect all Windy cameras before DB upsert phase.

    This allows stable `total_found` prior to processing, keeping UI progress
    meaningful during RUNNING state.
    """
    collected: list[dict[str, Any]] = []
    async for camera_data in scrape_all(
        target_country_code=target_country_code,
        max_pages=max_pages,
        start_page=start_page,
    ):
        collected.append(camera_data)
    return collected
