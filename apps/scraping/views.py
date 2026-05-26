from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from apps.scraping.config import get_insecam_country_codes, get_insecam_countries_with_labels, is_allowed_insecam_country
from apps.scraping.models import ScrapeJob, ScrapeJobStatus

logger = logging.getLogger(__name__)

SCRAPE_COOLDOWN_MINUTES = 30


class ScrapeJobListView(LoginRequiredMixin, ListView):
    model = ScrapeJob
    template_name = "scraping/job_list.html"
    context_object_name = "jobs"
    paginate_by = 30

    def get_queryset(self):
        qs = ScrapeJob.objects.all()
        if source := self.request.GET.get("source"):
            qs = qs.filter(source_type=source)
        if status := self.request.GET.get("status"):
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = ScrapeJobStatus.choices
        ctx["insecam_country_codes"] = get_insecam_country_codes()
        ctx["insecam_countries"] = get_insecam_countries_with_labels()
        return ctx


class ScrapeJobDetailView(LoginRequiredMixin, DetailView):
    model = ScrapeJob
    template_name = "scraping/job_detail.html"
    context_object_name = "job"


class TriggerScrapeView(LoginRequiredMixin, View):
    @staticmethod
    def _has_online_workers() -> bool:
        """Best-effort worker availability check before enqueueing tasks."""
        try:
            from celery import current_app

            inspector = current_app.control.inspect(timeout=1.0)
            pings = inspector.ping() if inspector else None
            return bool(pings)
        except Exception:
            return False

    def post(self, request):
        source = request.POST.get("source_type")
        country_code = (request.POST.get("insecam_country_code") or "").strip().upper()

        if source not in {"INSECAM", "WHATSUPCAMS"}:
            logger.warning("Invalid scrape source submitted by user=%s: %s", request.user, source)
            messages.error(request, "Choose a valid scrape source.")
            return redirect("scraping:job_list")

        if source == "INSECAM" and not country_code:
            messages.error(request, "Choose a country for Insecam scrape.")
            return redirect("scraping:job_list")

        if source == "INSECAM" and not is_allowed_insecam_country(country_code):
            messages.error(request, f"Country '{country_code}' is not enabled in INSECAM_COUNTRY_CODES config.")
            return redirect("scraping:job_list")

        active_filters = {
            "source_type": source,
            "status__in": [ScrapeJobStatus.PENDING, ScrapeJobStatus.RUNNING],
        }
        if source == "INSECAM":
            active_filters["target_country_code"] = country_code

        active_job = ScrapeJob.objects.filter(**active_filters).order_by("-created_at").first()
        if active_job:
            target_suffix = f" ({active_job.target_country_code})" if active_job.target_country_code else ""
            messages.warning(
                request,
                f"{source}{target_suffix} already has an active job (#{active_job.pk}, {active_job.status}).",
            )
            return redirect("scraping:job_list")

        cooldown_cutoff = timezone.now() - timedelta(minutes=SCRAPE_COOLDOWN_MINUTES)
        cooldown_filters = {
            "source_type": source,
            "created_at__gte": cooldown_cutoff,
        }
        if source == "INSECAM":
            cooldown_filters["target_country_code"] = country_code

        recent_job_exists = ScrapeJob.objects.filter(**cooldown_filters).exists()
        if recent_job_exists:
            messages.warning(
                request,
                f"{source} scrape was triggered recently. Wait {SCRAPE_COOLDOWN_MINUTES} minutes before triggering again.",
            )
            return redirect("scraping:job_list")

        if not self._has_online_workers():
            messages.error(request, "No Celery workers are online. Start a worker and try again.")
            return redirect("scraping:job_list")

        if source == "INSECAM":
            from apps.scraping.tasks import scrape_insecam_job

            job = ScrapeJob.objects.create(
                source_type=source,
                target_country_code=country_code,
            )
            try:
                task = scrape_insecam_job.delay(job_id=job.pk)
            except Exception as exc:
                job.mark_failed(error=f"Queue enqueue failed: {exc}")
                logger.exception("Failed to enqueue Insecam scrape job #%s: %s", job.pk, exc)
                messages.error(request, "Failed to enqueue Insecam scrape. Check broker/worker status.")
                return redirect("scraping:job_list")

            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id"])
            logger.info(
                "Triggered Insecam scrape: task_id=%s country=%s job_id=%s by user=%s",
                task.id,
                country_code,
                job.pk,
                request.user,
            )
            messages.success(request, f"Insecam [{country_code}] scrape queued (job #{job.pk}): {task.id}")
        elif source == "WHATSUPCAMS":
            from apps.scraping.tasks import scrape_whatsupcams_job

            job = ScrapeJob.objects.create(source_type=source)
            try:
                task = scrape_whatsupcams_job.delay(job_id=job.pk)
            except Exception as exc:
                job.mark_failed(error=f"Queue enqueue failed: {exc}")
                logger.exception("Failed to enqueue WhatsUpCams scrape job #%s: %s", job.pk, exc)
                messages.error(request, "Failed to enqueue WhatsUpCams scrape. Check broker/worker status.")
                return redirect("scraping:job_list")

            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id"])
            logger.info("Triggered WUC scrape: task_id=%s job_id=%s by user=%s", task.id, job.pk, request.user)
            messages.success(request, f"WhatsUpCams scrape queued (job #{job.pk}): {task.id}")
        return redirect("scraping:job_list")


class CancelScrapeView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        job = get_object_or_404(ScrapeJob, pk=pk)

        if job.is_terminal:
            messages.info(request, f"Job #{job.pk} is already {job.status}.")
            return redirect("scraping:job_list")

        if job.celery_task_id:
            from celery.result import AsyncResult

            AsyncResult(job.celery_task_id).revoke(terminate=True, signal="SIGTERM")

        job.mark_cancelled(reason=f"Cancelled by {request.user}")
        logger.info("Cancelled scrape job #%s by user=%s", job.pk, request.user)
        messages.success(request, f"Cancelled scrape job #{job.pk}.")
        return redirect("scraping:job_list")


# ── HTMX partials ────────────────────────────────────────────────────────────

class HtmxJobListView(LoginRequiredMixin, ListView):
    model = ScrapeJob
    template_name = "htmx/scraping/_job_row.html"
    context_object_name = "jobs"

    def get_queryset(self):
        return ScrapeJob.objects.all()[:20]


class HtmxJobRowView(LoginRequiredMixin, View):
    def get(self, request, pk: int):
        job = get_object_or_404(ScrapeJob, pk=pk)
        from django.template.loader import render_to_string

        html = render_to_string(
            "htmx/scraping/_job_row.html",
            {"jobs": [job]},
            request=request,
        )
        return HttpResponse(html)
