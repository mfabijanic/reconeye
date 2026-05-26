from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


def _create_and_run(source_type: str, self_task, *, target_country_code: str = "") -> dict:
    from apps.scraping.models import ScrapeJob
    from apps.scraping.services import run_scrape_job

    job = ScrapeJob.objects.create(
        source_type=source_type,
        target_country_code=target_country_code,
        celery_task_id=self_task.request.id or "",
    )
    try:
        run_scrape_job(job)
    except Exception as exc:
        job.mark_failed(error=str(exc))
        raise self_task.retry(exc=exc)
    return {
        "job_id": job.pk,
        "status": job.status,
        "total_new": job.total_new,
        "total_updated": job.total_updated,
    }


@shared_task(
    bind=True,
    name="reconeye.scraping.scrape_insecam",
    max_retries=2,
    default_retry_delay=300,
)
def scrape_insecam(self, country_code: str = "") -> dict:
    from apps.cameras.models import SourceType

    return _create_and_run(SourceType.INSECAM, self, target_country_code=country_code.strip().upper())


@shared_task(
    bind=True,
    name="reconeye.scraping.scrape_whatsupcams",
    max_retries=2,
    default_retry_delay=300,
)
def scrape_whatsupcams(self) -> dict:
    from apps.cameras.models import SourceType

    return _create_and_run(SourceType.WHATSUPCAMS, self)
