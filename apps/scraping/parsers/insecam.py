"""Insecam.org scraper.

Supports country-targeted scraping via /en/bycountry/<CODE>/?page=<N>.

Respectful scraping guidelines:
  - 1 request/second max (rate limiter)
  - Random 1-3s delay between listing pages (avoids pattern detection)
  - User-Agent rotation (in http.py)
  - Only enrich cameras that need it (missing stream_url)
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from apps.cameras.models import SourceType
from apps.scraping.http import build_client, get_limiter

logger = logging.getLogger(__name__)

BASE_URL = "http://www.insecam.org"
# 1 request/second = respectful scraping, no hammering
LIMITER = get_limiter(max_rate=1, time_period=1)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    async with LIMITER:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_labeled_value(soup: BeautifulSoup, label: str) -> str:
    target = f"{label}:"
    node = soup.find(string=lambda s: isinstance(s, str) and s.strip().startswith(target))
    if not node:
        return ""

    next_text = node.parent.find_next(
        string=lambda s: isinstance(s, str) and s.strip() and s.strip() != target
    )
    return next_text.strip() if next_text else ""


def parse_camera_page(html: str, page_url: str, base_data: dict[str, Any]) -> dict[str, Any]:
    """Extract camera data from an Insecam camera detail page."""
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else base_data.get("title", "")

    img = soup.find("img", id=re.compile(r"image\d*"))
    if img and img.get("src", ""):
        stream_url = img["src"]
    else:
        match = re.search(r'src\s*=\s*["\']([^"\']+\.jpg[^"\']*)["\']', html)
        stream_url = match.group(1) if match else ""

    country = _extract_labeled_value(soup, "Country")
    country_code = _extract_labeled_value(soup, "Country code").upper()
    region = _extract_labeled_value(soup, "Region")
    city = _extract_labeled_value(soup, "City")
    lat = _safe_float(_extract_labeled_value(soup, "Latitude"))
    lon = _safe_float(_extract_labeled_value(soup, "Longitude"))
    zip_code = _extract_labeled_value(soup, "ZIP")
    timezone = _extract_labeled_value(soup, "Timezone")
    manufacturer = _extract_labeled_value(soup, "Manufacturer")

    source_payload = {
        **(base_data.get("source_payload") or {}),
        "page_url": page_url,
        "country": country,
        "country_code": country_code,
        "region": region,
        "city": city,
        "latitude": lat,
        "longitude": lon,
        "zip": zip_code,
        "timezone": timezone,
        "manufacturer": manufacturer,
    }

    return {
        "source_type": SourceType.INSECAM,
        "title": title,
        "page_url": page_url,
        "preview_image": base_data.get("preview_image", "") or stream_url,
        "stream_url": stream_url,
        "country": country,
        "country_code": country_code,
        "region": region,
        "city": city,
        "latitude": lat,
        "longitude": lon,
        "zip_code": zip_code,
        "timezone": timezone,
        "manufacturer": manufacturer,
        "has_partial_metadata": not bool(stream_url),
        "source_payload": source_payload,
    }


async def _should_enrich_camera(base_data: dict[str, Any]) -> bool:
    """Check if a camera record needs enrichment.
    
    Skip enrichment if we already have a valid stream_url from listing.
    Enrichment is only needed for cameras with missing stream URLs.
    """
    stream_url = base_data.get("stream_url", "").strip()
    # Only enrich if stream_url is empty/missing
    return not bool(stream_url)


def _listing_url(*, page: int, country_code: str | None) -> str:
    if country_code:
        return f"{BASE_URL}/en/bycountry/{country_code}/?page={page}"
    return f"{BASE_URL}/en/byrating/?page={page}"


async def scrape_listing_page(
    client: httpx.AsyncClient,
    *,
    page: int = 1,
    country_code: str | None = None,
) -> list[dict[str, Any]]:
    """Scrape one Insecam listing page and return partial camera dicts."""
    url = _listing_url(page=page, country_code=country_code)
    try:
        html = await fetch_page(client, url)
    except Exception as exc:
        logger.warning("Failed to fetch Insecam listing page %d (%s): %s", page, country_code or "ALL", exc)
        return []

    soup = BeautifulSoup(html, "lxml")
    cameras: list[dict[str, Any]] = []

    for thumbnail in soup.select("div.thumbnail-item, div.camera-item, div.thumbnail"):
        link_tag = thumbnail.find("a", href=True)
        img_tag = thumbnail.find("img")
        if not link_tag:
            continue

        href = link_tag["href"]
        page_url = BASE_URL + href if not href.startswith("http") else href
        preview = img_tag["src"] if img_tag and img_tag.get("src") else ""

        cameras.append(
            {
                "source_type": SourceType.INSECAM,
                "title": link_tag.get("title", ""),
                "page_url": page_url,
                "preview_image": preview,
                "stream_url": preview,
                "country_code": country_code or "",
                "has_partial_metadata": not bool(preview),
                "source_payload": {"listing_img": preview, "page_url": page_url},
            }
        )

    return cameras


async def collect_listing(
    client: httpx.AsyncClient,
    *,
    country_code: str | None,
    max_pages: int,
    on_page: Any = None,
) -> list[dict[str, Any]]:
    """Collect all camera listing URLs.

    ``on_page`` is an optional async callable called after each page with the
    running total discovered so far, signature: ``await on_page(total: int)``.
    """
    listing: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        items = await scrape_listing_page(client, page=page, country_code=country_code)
        if not items:
            if page == 1:
                scope = country_code or "ALL"
                raise RuntimeError(f"Insecam returned no data on first page for scope={scope}.")
            break

        new_on_page = 0
        for item in items:
            page_url = item.get("page_url", "")
            if page_url in seen:
                continue
            seen.add(page_url)
            listing.append(item)
            new_on_page += 1

        # Insecam repeats page 1 content for out-of-bounds pages — stop when
        # a page adds no new cameras (all URLs already seen).
        if new_on_page == 0:
            logger.debug("Insecam listing: page %d added 0 new cameras, stopping.", page)
            break

        if on_page is not None:
            await on_page(len(listing))

        # Random delay between pages: 1-3 seconds (respectful scraping)
        # This avoids hammering the server and pattern detection
        delay = random.uniform(1.0, 3.0)
        await asyncio.sleep(delay)

    return listing


async def enrich_camera_details(client: httpx.AsyncClient, base_data: dict[str, Any]) -> dict[str, Any]:
    page_url = base_data["page_url"]
    try:
        html = await fetch_page(client, page_url)
        return parse_camera_page(html, page_url, base_data=base_data)
    except Exception as exc:
        logger.warning("Insecam detail fetch failed for %s: %s", page_url, exc)
        fallback_payload = {
            **(base_data.get("source_payload") or {}),
            "detail_error": str(exc),
        }
        return {
            **base_data,
            "has_partial_metadata": True,
            "source_payload": fallback_payload,
        }
    finally:
        # Small random delay after detail fetch to be respectful
        await asyncio.sleep(random.uniform(0.3, 0.7))


async def scrape_cameras(
    *,
    country_code: str | None,
    max_pages: int = 200,
) -> list[dict[str, Any]]:
    """Collect, then enrich camera records for deterministic total_found/progress."""
    normalized_country = (country_code or "").strip().upper() or None

    async with build_client() as client:
        listing = await collect_listing(
            client,
            country_code=normalized_country,
            max_pages=max_pages,
        )

        result: list[dict[str, Any]] = []
        for item in listing:
            result.append(await enrich_camera_details(client, item))
        return result
