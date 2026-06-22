from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.cameras.models import SourceType
from apps.scraping.models import ScrapeJob, ScrapeJobStatus
from apps.users.models import User


def test_dashboard_renders_sidebar_for_authenticated_user(client, db) -> None:
    user = User.objects.create_user(username="dash-user", password="pw")
    client.force_login(user)

    response = client.get(reverse("dashboard:index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="appSidebar"' in content
    assert "Scrape Jobs" in content
    assert "go2rtc Viewer" in content
    assert "go2rtc Manager" in content
    assert reverse("dashboard_htmx:htmx_active_jobs") in content


@override_settings(RECON_EYE_CAPABILITIES={"go2rtc_manager": False})
def test_dashboard_hides_disabled_go2rtc_navigation(client, db) -> None:
    user = User.objects.create_user(username="dash-cap-user", password="pw")
    client.force_login(user)

    response = client.get(reverse("dashboard:index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "go2rtc Viewer" not in content
    assert "go2rtc Manager" not in content


def test_dashboard_active_jobs_htmx_limits_to_10_latest_jobs(client, db) -> None:
    user = User.objects.create_user(username="dash-jobs-user", password="pw")
    client.force_login(user)

    base = timezone.now()
    jobs: list[ScrapeJob] = []
    statuses = [
        ScrapeJobStatus.PENDING,
        ScrapeJobStatus.RUNNING,
        ScrapeJobStatus.SUCCESS,
        ScrapeJobStatus.FAILED,
        ScrapeJobStatus.CANCELLED,
    ]
    for idx in range(12):
        job = ScrapeJob.objects.create(source_type=SourceType.INSECAM, status=statuses[idx % len(statuses)])
        ScrapeJob.objects.filter(pk=job.pk).update(created_at=base + timedelta(minutes=idx))
        job.refresh_from_db(fields=["created_at"])
        jobs.append(job)

    response = client.get(reverse("dashboard_htmx:htmx_active_jobs"))

    assert response.status_code == 200
    content = response.content.decode()

    for job in jobs[-10:]:
        assert f">{job.pk}</td>" in content

    for job in jobs[:2]:
        assert f">{job.pk}</td>" not in content
