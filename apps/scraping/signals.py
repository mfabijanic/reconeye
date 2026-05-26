from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


@receiver([post_save, post_delete], sender="scraping.ScrapeJob")
def scrape_job_changed(sender, instance, **kwargs) -> None:
    from apps.common.cache import invalidate_scrape_jobs

    invalidate_scrape_jobs()
