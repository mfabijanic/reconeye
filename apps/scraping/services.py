from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

from asgiref.sync import sync_to_async

from apps.cameras.models import Camera, SourceType
from apps.cameras.services import upsert_camera
from apps.scraping.geolocation import resolve_location_candidates
from apps.scraping.models import GeoLocationCache, GeoLocationProvider
from apps.scraping.models import ScrapeJob
from apps.scraping.parsers.whatsupcams import (
    COUNTRY_NAMES,
    _build_location_candidates,
    _country_code_from_stream_id,
    _resolve_camera_title,
    _resolve_city_fallback,
)

logger = logging.getLogger(__name__)

# Smaller batch size gives smoother progress updates in UI during RUNNING state.
BATCH_SIZE = 10


def _normalize_geo_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def _stream_id_from_camera(camera: Camera) -> str:
    payload = dict(camera.source_payload or {})
    payload_stream_id = str(payload.get("stream_id") or "").strip().lower()
    if payload_stream_id:
        return payload_stream_id

    title_stream_id = str(camera.title or "").strip().lower()
    if _country_code_from_stream_id(title_stream_id):
        return title_stream_id

    parsed = urlparse(camera.page_url or "")
    slug = (parsed.path or "").strip("/").split("/")[-1].strip().lower()
    return slug


def _rebuild_wuc_candidates(camera: Camera) -> list[str] | None:
    """Rebuild candidates using current WUC mappings for existing camera rows."""
    stream_id = _stream_id_from_camera(camera)
    if not stream_id or not _country_code_from_stream_id(stream_id):
        return None

    stream_payload = dict((camera.source_payload or {}).get("stream_payload") or {})
    country_code = _country_code_from_stream_id(stream_id)
    country_name = COUNTRY_NAMES.get(country_code, country_code)
    return _build_location_candidates(
        stream_id,
        stream_payload,
        country_code=country_code,
        country_name=country_name,
    )


def refresh_geolocation_for_camera_ids(camera_ids: list[int]) -> dict[str, int]:
    """Force-refresh geolocation cache entries and coordinates for selected cameras.

    Intended for targeted maintenance after mapping fixes. For each selected camera:
    - takes stored location candidates,
    - removes candidate cache entries for the same country code,
    - re-runs candidate resolution against Nominatim,
    - updates camera geo fields and `source_payload.geocoded`.
    """
    ids = [int(pk) for pk in camera_ids if pk is not None]
    if not ids:
        return {"requested": 0, "processed": 0, "updated": 0, "failed": 0, "skipped": 0}

    processed = 0
    updated = 0
    failed = 0
    skipped = 0

    cameras = Camera.objects.filter(id__in=ids).order_by("id")
    for camera in cameras:
        processed += 1
        payload = dict(camera.source_payload or {})
        raw_candidates = payload.get("location_candidates") or []
        wuc_stream_id = ""
        wuc_stream_payload: dict[str, Any] = {}

        if camera.source_type == SourceType.WHATSUPCAMS:
            wuc_stream_id = _stream_id_from_camera(camera)
            wuc_stream_payload = dict(payload.get("stream_payload") or {})
            rebuilt_candidates = _rebuild_wuc_candidates(camera)
            if rebuilt_candidates:
                raw_candidates = rebuilt_candidates
                payload["location_candidates"] = rebuilt_candidates
            if wuc_stream_id:
                payload["stream_id"] = wuc_stream_id

        candidates = [str(item).strip() for item in raw_candidates if isinstance(item, str) and item.strip()]
        if not candidates:
            skipped += 1
            continue

        country_code = (camera.country_code or "").strip().upper()
        normalized_candidates = [_normalize_geo_query(item) for item in candidates]
        normalized_candidates = [item for item in normalized_candidates if item]

        if normalized_candidates:
            GeoLocationCache.objects.filter(
                provider=GeoLocationProvider.NOMINATIM,
                country_code=country_code,
                normalized_query__in=normalized_candidates,
            ).delete()

        try:
            geocoded = asyncio.run(
                resolve_location_candidates(candidates, country_code=country_code)
            )
        except Exception:
            logger.exception("Failed to refresh geolocation for camera_id=%s", camera.id)
            failed += 1
            continue

        geocode_payload = {
            "found": bool(geocoded.get("found", False)),
            "from_cache": bool(geocoded.get("from_cache", False)),
            "query": str(geocoded.get("query") or ""),
            "display_name": str(geocoded.get("display_name") or ""),
        }
        payload["geocoded"] = geocode_payload
        camera.source_payload = payload

        changed_fields: list[str] = ["source_payload", "updated_at"]

        def _set_if_changed(field: str, value: Any) -> None:
            nonlocal changed_fields
            if getattr(camera, field) != value:
                setattr(camera, field, value)
                if field not in changed_fields:
                    changed_fields.append(field)

        _set_if_changed("latitude", geocoded.get("latitude"))
        _set_if_changed("longitude", geocoded.get("longitude"))
        _set_if_changed("region", str(geocoded.get("region") or ""))
        _set_if_changed("zip_code", str(geocoded.get("zip_code") or ""))

        city = str(geocoded.get("city") or "").strip()
        if not city and camera.source_type == SourceType.WHATSUPCAMS and wuc_stream_id:
            fallback_code = (camera.country_code or _country_code_from_stream_id(wuc_stream_id)).strip().upper()
            city = _resolve_city_fallback(wuc_stream_id, country_code=fallback_code)
        if city:
            _set_if_changed("city", city)

        raw_country = str(
            (geocoded.get("raw_payload") or {}).get("address", {}).get("country") or ""
        ).strip()
        if raw_country:
            _set_if_changed("country", raw_country)

        if camera.source_type == SourceType.WHATSUPCAMS and wuc_stream_id:
            title_code = (camera.country_code or _country_code_from_stream_id(wuc_stream_id)).strip().upper()
            resolved_title = _resolve_camera_title(
                wuc_stream_id,
                wuc_stream_payload,
                country_code=title_code,
                city=city,
            )
            if resolved_title:
                _set_if_changed("title", resolved_title)
                if payload.get("resolved_title") != resolved_title:
                    payload["resolved_title"] = resolved_title
                    camera.source_payload = payload

        camera.save(update_fields=changed_fields)
        updated += 1

    return {
        "requested": len(ids),
        "processed": processed,
        "updated": updated,
        "failed": failed,
        "skipped": skipped,
    }


def run_scrape_job(job: ScrapeJob, *, resolve_streams: bool = True) -> None:
    """
    Synchronous entry point for Celery tasks.
    Wraps the async scraper in an event loop.
    """
    asyncio.run(_run_scrape(job, resolve_streams=resolve_streams))


async def _run_scrape(job: ScrapeJob, *, resolve_streams: bool = True) -> None:
    await sync_to_async(job.mark_running, thread_sensitive=True)()
    total_new = 0
    total_updated = 0
    total_processed = 0

    try:
        if job.source_type == SourceType.INSECAM:
            from apps.scraping.parsers.insecam import (
                collect_listing,
                enrich_camera_details,
                _should_enrich_camera,
            )
            from apps.scraping.http import build_client

            country = (job.target_country_code or None)

            async with build_client() as client:
                # Phase 1: collect all listing URLs; update total_found after each page
                # so the UI shows discovery progress instead of 0% the whole time.
                async def _on_listing_page(discovered: int) -> None:
                    await sync_to_async(job.update_counters, thread_sensitive=True)(found=discovered)

                listing = await collect_listing(
                    client, country_code=country, max_pages=200, on_page=_on_listing_page
                )
                total_found = len(listing)
                await sync_to_async(job.update_counters, thread_sensitive=True)(found=total_found)

                # Phase 2: enrich only cameras that need it (missing stream_url), then flush
                # This skips enrichment for ~95% of cameras that already have stream URLs
                # from the listing page, dramatically reducing HTTP requests.
                for start in range(0, total_found, BATCH_SIZE):
                    chunk = listing[start : start + BATCH_SIZE]
                    enriched = []
                    for base_data in chunk:
                        if await _should_enrich_camera(base_data):
                            # Needs detail page fetch → enrich it
                            enriched.append(await enrich_camera_details(client, base_data))
                        else:
                            # Already has stream_url from listing → use as-is
                            enriched.append(base_data)
                    chunk_size = len(enriched)
                    new, updated = await _flush_batch_async(enriched)
                    total_new += new
                    total_updated += updated
                    total_processed += chunk_size
                    await sync_to_async(job.update_counters, thread_sensitive=True)(
                        found=total_found,
                        processed=chunk_size,
                        new=new,
                        updated=updated,
                    )
        elif job.source_type == SourceType.WHATSUPCAMS:
            from apps.scraping.parsers.whatsupcams import scrape_all

            batch: list[dict[str, Any]] = []
            discovered = 0
            async for camera_data in scrape_all(
                target_country_code=(job.target_country_code or None),
            ):
                discovered += 1
                batch.append(camera_data)
                if len(batch) >= BATCH_SIZE:
                    batch_size = len(batch)
                    new, updated = await _flush_batch_async(batch)
                    total_new += new
                    total_updated += updated
                    total_processed += batch_size
                    batch.clear()
                    await sync_to_async(job.update_counters, thread_sensitive=True)(
                        found=discovered,
                        processed=batch_size,
                        new=new,
                        updated=updated,
                    )

            if batch:
                batch_size = len(batch)
                new, updated = await _flush_batch_async(batch)
                total_new += new
                total_updated += updated
                total_processed += batch_size
                await sync_to_async(job.update_counters, thread_sensitive=True)(
                    found=discovered,
                    processed=batch_size,
                    new=new,
                    updated=updated,
                )
        else:
            raise ValueError(f"Unknown source_type: {job.source_type}")

        await sync_to_async(job.mark_success, thread_sensitive=True)()
        logger.info(
            "Scrape job %d finished: new=%d updated=%d processed=%d",
            job.pk,
            total_new,
            total_updated,
            total_processed,
        )
    except Exception as exc:
        await sync_to_async(job.mark_failed, thread_sensitive=True)(error=str(exc))
        logger.exception("Scrape job %d failed: %s", job.pk, exc)
        raise


async def _flush_batch_async(batch: list[dict[str, Any]]) -> tuple[int, int]:
    new = 0
    updated = 0
    for data in batch:
        try:
            _, created = await sync_to_async(upsert_camera, thread_sensitive=True)(data)
            if created:
                new += 1
            else:
                updated += 1
        except Exception as exc:
            logger.warning("Failed to upsert camera %s: %s", data.get("page_url"), exc)
    return new, updated
