from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from django.conf import settings

app = Celery("reconeye")

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Scraping
    "scrape-insecam-daily": {
        "task": "reconeye.scraping.scrape_insecam",
        "schedule": crontab(hour=3, minute=0),
    },
    "scrape-whatsupcams-daily": {
        "task": "reconeye.scraping.scrape_whatsupcams",
        "schedule": crontab(hour=4, minute=0),
    },
    # Camera status checks — every 15 minutes
    "refresh-camera-status": {
        "task": "reconeye.cameras.refresh_camera_status",
        "schedule": crontab(minute="*/15"),
    },
    # Maintenance
    "cleanup-old-logs-daily": {
        "task": "reconeye.cameras.cleanup_old_logs",
        "schedule": crontab(hour=2, minute=0),
    },
    # Cache warm-up after scrape runs
    "warm-cache-hourly": {
        "task": "reconeye.cameras.warm_cache",
        "schedule": crontab(minute=30),
    },
}
