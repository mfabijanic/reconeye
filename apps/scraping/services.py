from __future__ import annotations

import asyncio
import logging
from typing import Any

from asgiref.sync import sync_to_async

from apps.cameras.models import SourceType
from apps.cameras.services import upsert_camera
from apps.scraping.models import ScrapeJob

logger = logging.getLogger(__name__)

# Smaller batch size gives smoother progress updates in UI during RUNNING state.
BATCH_SIZE = 10


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
            async for camera_data in scrape_all():
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
