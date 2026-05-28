from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="reconeye.cameras.refresh_camera_status",
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    default_retry_delay=60,
)
def refresh_camera_status(self) -> dict:
    """Check connectivity for all active cameras and update is_online flag."""
    from apps.cameras.models import Camera

    cameras = Camera.objects.filter(is_active=True).exclude(stream_url="")
    updated = 0
    errors = 0

    for camera in cameras.iterator(chunk_size=200):
        try:
            import httpx

            with httpx.Client(timeout=5) as client:
                resp = client.head(camera.stream_url)
            online = resp.status_code < 400
        except Exception:
            online = False
            errors += 1

        if online:
            camera.mark_online()
        else:
            camera.mark_offline()
        updated += 1

    logger.info("refresh_camera_status: updated=%d errors=%d", updated, errors)
    return {"updated": updated, "errors": errors}


@shared_task(
    bind=True,
    name="reconeye.cameras.check_single_camera_status",
    max_retries=0,
)
def check_single_camera_status(self, camera_id: int) -> dict:
    """Check stream_url availability for a single camera and update is_online flag."""
    from apps.cameras.models import Camera

    try:
        camera = Camera.objects.get(pk=camera_id, is_active=True)
    except Camera.DoesNotExist:
        logger.warning("check_single_camera_status: camera %d not found", camera_id)
        return {"error": "not_found"}

    if not camera.stream_url:
        logger.info("check_single_camera_status: camera %d has no stream_url, skipping", camera_id)
        return {"skipped": True, "reason": "no_stream_url"}

    try:
        import httpx

        with httpx.Client(timeout=6, follow_redirects=True) as client:
            resp = client.head(camera.stream_url)
        online = resp.status_code < 400
    except Exception as exc:
        logger.info("check_single_camera_status: camera %d unreachable: %s", camera_id, exc)
        online = False

    if online:
        camera.mark_online()
    else:
        camera.mark_offline()

    logger.info("check_single_camera_status: camera %d is_online=%s", camera_id, online)
    return {"camera_id": camera_id, "is_online": online}


@shared_task(
    bind=True,
    name="reconeye.cameras.cleanup_old_logs",
    max_retries=2,
)
def cleanup_old_logs(self) -> dict:
    from apps.cameras.services import cleanup_check_logs

    deleted = cleanup_check_logs()
    return {"deleted": deleted}


@shared_task(
    bind=True,
    name="reconeye.cameras.warm_cache",
    max_retries=2,
)
def warm_cache(self) -> dict:
    from apps.cameras.services import get_camera_list, get_country_choices
    from apps.common.cache import TTL_WARM, versioned_key, DOMAIN_CAMERAS, DOMAIN_DASHBOARD
    from django.core.cache import cache
    from apps.cameras.models import SourceType

    get_country_choices()
    for src in [None, SourceType.INSECAM, SourceType.WHATSUPCAMS]:
        get_camera_list(source_type=src, page=1)

    # Warm dashboard stats
    from apps.dashboard.services import get_dashboard_stats

    stats = get_dashboard_stats(force=True)
    logger.info("warm_cache: done, stats=%s", stats)
    return stats
