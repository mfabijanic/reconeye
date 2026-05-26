"""
WhatsUpCams scraper

WhatsUpCams embeds camera streams via iframes. If the direct stream URL
cannot be extracted, we store page_url and set has_partial_metadata=True.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from apps.cameras.models import SourceType
from apps.scraping.http import build_client, get_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.whatsupcams.com"
API_URL = f"{BASE_URL}/en/cameras/"
LIMITER = get_limiter(max_rate=2, time_period=1)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=3, max=15))
async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    async with LIMITER:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def extract_stream_from_html(html: str) -> str:
    """
    Try to extract a direct playable stream URL from a WhatsUpCams camera page.
    Looks for M3U8, RTSP, or direct MJPEG URLs embedded in JS or iframes.
    """
    # M3U8 stream
    m = re.search(r'["\']([^"\']+\.m3u8[^"\']*)["\']', html)
    if m:
        return m.group(1)

    # Direct MJPEG or MP4 stream
    m = re.search(r'["\']([^"\']+\.(mjpg|mjpeg|mp4)[^"\']*)["\']', html, re.I)
    if m:
        return m.group(1)

    # Iframe src that points to a stream service
    soup = BeautifulSoup(html, "lxml")
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if any(keyword in src for keyword in ["embed", "stream", "cam", "live"]):
            return src

    return ""


def parse_camera_list_page(html: str) -> list[dict]:
    """Parse the WhatsUpCams camera listing page and return partial camera dicts."""
    soup = BeautifulSoup(html, "lxml")
    cameras = []

    for card in soup.select("div.camera-card, article.camera, div[class*='cam']"):
        link = card.find("a", href=True)
        img = card.find("img")
        title_tag = card.find(["h2", "h3", "h4", ".camera-title", ".title"])

        if not link:
            continue

        href = link["href"]
        page_url = href if href.startswith("http") else BASE_URL + href
        preview = img["src"] if img and img.get("src") else ""
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Try to infer country from URL or card metadata
        country = ""
        city = ""
        country_tag = card.find(class_=re.compile(r"country|location", re.I))
        if country_tag:
            text = country_tag.get_text(strip=True)
            parts = [p.strip() for p in text.split(",")]
            if len(parts) >= 2:
                country, city = parts[0], parts[1]
            elif parts:
                country = parts[0]

        cameras.append({
            "source_type": SourceType.WHATSUPCAMS,
            "title": title,
            "page_url": page_url,
            "preview_image": preview,
            "stream_url": "",  # resolved later per-camera
            "country": country,
            "city": city,
            "has_partial_metadata": True,  # will be updated after detail fetch
            "source_payload": {
                "page_url": page_url,
                "preview_image": preview,
                "title": title,
            },
        })

    return cameras


async def resolve_camera_stream(client: httpx.AsyncClient, cam: dict) -> dict:
    """
    Fetch the camera detail page and try to extract a direct stream URL.
    If unsuccessful, cam remains with has_partial_metadata=True.
    """
    try:
        html = await fetch_page(client, cam["page_url"])
        stream_url = extract_stream_from_html(html)
        if stream_url:
            cam["stream_url"] = stream_url
            cam["has_partial_metadata"] = False
        else:
            cam["has_partial_metadata"] = True
            logger.debug("WUC: no direct stream for %s", cam["page_url"])
    except Exception as exc:
        logger.warning("WUC: failed to resolve stream for %s: %s", cam["page_url"], exc)
        cam["has_partial_metadata"] = True
    return cam


async def get_total_pages(client: httpx.AsyncClient) -> int:
    html = await fetch_page(client, API_URL)
    soup = BeautifulSoup(html, "lxml")
    last = soup.select("ul.pagination li:last-child a, .pagination a:last-child")
    if last:
        href = last[0].get("href", "")
        m = re.search(r"[?&]page=(\d+)", href)
        if m:
            return int(m.group(1))
    return 1


async def scrape_all(resolve_streams: bool = True, max_pages: int = 100) -> AsyncIterator[dict]:
    """
    Async generator yielding camera dicts scraped from WhatsUpCams.

    If resolve_streams=True, fetches each camera detail page to get stream URL.
    Otherwise, sets has_partial_metadata=True for all.
    """
    async with build_client() as client:
        try:
            total_pages = await get_total_pages(client)
        except Exception as exc:
            logger.error("WUC: failed to get total pages: %s", exc)
            total_pages = 1

        total_pages = min(total_pages, max_pages)
        logger.info("WUC: scraping %d pages", total_pages)

        for page in range(1, total_pages + 1):
            url = f"{API_URL}?page={page}"
            try:
                html = await fetch_page(client, url)
            except Exception as exc:
                logger.warning("WUC: failed page %d: %s", page, exc)
                continue

            cameras = parse_camera_list_page(html)
            if not cameras:
                logger.info("WUC: no cameras on page %d, stopping.", page)
                break

            if resolve_streams:
                tasks = [resolve_camera_stream(client, cam) for cam in cameras]
                resolved = await asyncio.gather(*tasks, return_exceptions=False)
                for cam in resolved:
                    yield cam
            else:
                for cam in cameras:
                    yield cam

            await asyncio.sleep(0.5)
