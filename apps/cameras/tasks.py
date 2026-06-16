from __future__ import annotations

import logging
import time

from celery import shared_task
from django.db import OperationalError, connection
from django.db.transaction import TransactionManagementError

from apps.common.celery_activity import track_task_activity

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

    with track_task_activity(refresh_camera_status.name, self.request.id or ""):
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
    """
    Check stream_url availability for a single camera.
    For HLS streams, attempts to fetch, validate playlist, and verify segment URLs.
    Updates is_online flag and returns detailed result.
    """
    from apps.cameras.models import Camera

    with track_task_activity(check_single_camera_status.name, self.request.id or ""):
        try:
            camera = Camera.objects.get(pk=camera_id, is_active=True)
        except Camera.DoesNotExist:
            logger.warning("check_single_camera_status: camera %d not found", camera_id)
            return {"error": "not_found"}

        if not camera.stream_url:
            logger.info("check_single_camera_status: camera %d has no stream_url, skipping", camera_id)
            return {"skipped": True, "reason": "no_stream_url"}

        online = False
        error_msg = ""

        try:
            import httpx

            with httpx.Client(timeout=8, follow_redirects=True) as client:
                # For HLS, attempt to fetch playlist and validate segments
                if ".m3u8" in camera.stream_url.lower():
                    try:
                        resp = client.get(camera.stream_url)
                        if resp.status_code == 200:
                            content = resp.text.strip()
                            # Basic HLS playlist validation
                            if not content.startswith("#EXTM3U"):
                                error_msg = "Invalid HLS playlist format"
                            else:
                                # Try to extract and validate a segment URL from playlist
                                lines = content.split("\n")
                                playlist_url_base = camera.stream_url.rsplit("/", 1)[0]
                                segment_url = None

                                for line in lines:
                                    line = line.strip()
                                    if line and not line.startswith("#"):
                                        # This should be a segment file reference
                                        if line.startswith("http"):
                                            segment_url = line
                                        else:
                                            segment_url = f"{playlist_url_base}/{line}"
                                        break

                                if segment_url:
                                    # Try to fetch first segment to confirm stream is actually streaming
                                    try:
                                        seg_resp = client.head(segment_url, timeout=5)
                                        if seg_resp.status_code < 400:
                                            online = True
                                        else:
                                            error_msg = f"Segment HTTP {seg_resp.status_code}"
                                    except Exception as seg_exc:
                                        error_msg = f"Segment unreachable: {type(seg_exc).__name__}"
                                else:
                                    # No segments found (might be live stream without segments in playlist)
                                    # Assume online if playlist is valid
                                    online = True
                        else:
                            error_msg = f"HTTP {resp.status_code}"
                    except httpx.ReadTimeout:
                        error_msg = "Playlist read timeout"
                else:
                    # Non-HLS stream: HEAD request
                    resp = client.head(camera.stream_url)
                    online = resp.status_code < 400
                    if not online:
                        error_msg = f"HTTP {resp.status_code}"
        except httpx.ConnectError:
            error_msg = "Connection refused"
        except httpx.TimeoutException:
            error_msg = "Request timeout"
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {str(exc)[:50]}"

        if online:
            camera.mark_online()
        else:
            camera.mark_offline()

        logger.info(
            "check_single_camera_status: camera %d is_online=%s error=%s",
            camera_id,
            online,
            error_msg,
        )
        return {"camera_id": camera_id, "is_online": online, "error": error_msg}


@shared_task(
    bind=True,
    name="reconeye.cameras.cleanup_old_logs",
    max_retries=2,
)
def cleanup_old_logs(self) -> dict:
    from apps.cameras.services import cleanup_check_logs

    with track_task_activity(cleanup_old_logs.name, self.request.id or ""):
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

    with track_task_activity(warm_cache.name, self.request.id or ""):
        get_country_choices()
        for src in [None, SourceType.INSECAM, SourceType.WHATSUPCAMS]:
            get_camera_list(source_type=src, page=1)

        # Warm dashboard stats
        from apps.dashboard.services import get_dashboard_stats

        stats = get_dashboard_stats(force=True)
        logger.info("warm_cache: done, stats=%s", stats)
        return stats


@shared_task(
    bind=True,
    name="reconeye.cameras.sync_go2rtc_instance",
    max_retries=2,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def sync_go2rtc_instance_task(self, instance_id: int) -> dict:
    from apps.cameras.models import Go2RTCInstance
    from apps.cameras.services import sync_go2rtc_instance

    with track_task_activity(sync_go2rtc_instance_task.name, self.request.id or ""):
        instance = Go2RTCInstance.objects.get(pk=instance_id, is_active=True)
        count, error, warning = sync_go2rtc_instance(instance)
        if instance.last_sync_status == Go2RTCInstance.LastSyncStatus.UNAUTHORIZED:
            status = "unauthorized"
        elif error:
            status = "failed"
        else:
            status = "success"
        return {
            "instance_id": instance_id,
            "stream_count": count,
            "error": error,
            "warning": warning,
            "status": status,
        }


@shared_task(
    bind=True,
    name="reconeye.cameras.sync_go2rtc_instances_batch",
    max_retries=0,
)
def sync_go2rtc_instances_batch_task(self, instance_ids: list[int]) -> dict:
    """Sync imported go2rtc instances sequentially to reduce SQLite lock contention."""
    from apps.cameras.models import Go2RTCInstance
    from apps.cameras.services import sync_go2rtc_instance

    with track_task_activity(sync_go2rtc_instances_batch_task.name, self.request.id or ""):
        synced = 0
        failed = 0
        unauthorized = 0
        warnings = 0
        lock_retries = 0

        for instance_id in instance_ids or []:
            for attempt in range(3):
                try:
                    instance = Go2RTCInstance.objects.get(pk=instance_id, is_active=True)
                    _, error, warning = sync_go2rtc_instance(instance)

                    if instance.last_sync_status == Go2RTCInstance.LastSyncStatus.UNAUTHORIZED:
                        unauthorized += 1
                    elif error:
                        failed += 1
                    else:
                        synced += 1

                    if warning:
                        warnings += 1
                    break
                except Go2RTCInstance.DoesNotExist:
                    logger.warning(
                        "sync_go2rtc_instances_batch: instance %s not found or inactive",
                        instance_id,
                    )
                    failed += 1
                    break
                except (OperationalError, TransactionManagementError) as exc:
                    if attempt < 2:
                        lock_retries += 1
                        try:
                            connection.close()
                        except Exception:
                            pass
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    logger.exception(
                        "sync_go2rtc_instances_batch: db error for instance=%s",
                        instance_id,
                    )
                    failed += 1
                    break
                except Exception:
                    logger.exception(
                        "sync_go2rtc_instances_batch: unexpected error for instance=%s",
                        instance_id,
                    )
                    failed += 1
                    break

        logger.info(
            "sync_go2rtc_instances_batch: total=%d synced=%d failed=%d unauthorized=%d warnings=%d lock_retries=%d",
            len(instance_ids or []),
            synced,
            failed,
            unauthorized,
            warnings,
            lock_retries,
        )
        return {
            "total": len(instance_ids or []),
            "synced": synced,
            "failed": failed,
            "unauthorized": unauthorized,
            "warnings": warnings,
            "lock_retries": lock_retries,
        }
