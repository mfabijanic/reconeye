from __future__ import annotations

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.common.cache import invalidate_cameras

logger = logging.getLogger(__name__)


@receiver([post_save, post_delete], sender="cameras.Camera")
def camera_changed(sender, instance, **kwargs) -> None:
    invalidate_cameras()
    logger.debug("Camera cache invalidated for camera pk=%s", instance.pk)


@receiver([post_save, post_delete], sender="cameras.CameraCheckLog")
def check_log_changed(sender, instance, **kwargs) -> None:
    from apps.common.cache import invalidate_dashboard

    invalidate_dashboard()
