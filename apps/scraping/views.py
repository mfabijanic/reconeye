from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DetailView, ListView

from apps.scraping.config import (
    get_insecam_country_codes,
    get_insecam_countries_with_labels,
    get_whatsupcams_countries_with_labels,
    is_allowed_insecam_country,
    is_allowed_whatsupcams_country,
)
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
        ctx["whatsupcams_countries"] = get_whatsupcams_countries_with_labels()
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
        target_country_code = (request.POST.get("country_code") or "").strip().upper()
        windy_start_camera_raw = (request.POST.get("windy_start_camera") or "").strip()
        windy_block_count_raw = (request.POST.get("windy_block_count") or "").strip()
        windy_start_camera = 0
        windy_block_count = 1

        if source == "WINDY":
            if windy_start_camera_raw:
                try:
                    windy_start_camera = int(windy_start_camera_raw)
                except ValueError:
                    messages.error(request, _("Enter a valid Windy start camera."))
                    return redirect("scraping:job_list")

                if windy_start_camera < 0 or windy_start_camera % 1000 != 0:
                    messages.error(request, _("Windy start camera must be 0, 1000, 2000, and so on."))
                    return redirect("scraping:job_list")

                # Current Windy API tier supports offset up to 1000 only.
                if windy_start_camera > 1000:
                    messages.error(
                        request,
                        _("Windy start camera above 1000 is not available on the current API tier."),
                    )
                    return redirect("scraping:job_list")
            
            if windy_block_count_raw:
                try:
                    windy_block_count = int(windy_block_count_raw)
                except ValueError:
                    messages.error(request, _("Enter a valid number of Windy blocks."))
                    return redirect("scraping:job_list")
                
                if windy_block_count < 1 or windy_block_count > 20:
                    messages.error(request, _("Windy block count must be between 1 and 20."))
                    return redirect("scraping:job_list")

            # If starting at 1000, only one page-block is effectively available.
            if windy_start_camera == 1000 and windy_block_count > 1:
                messages.error(
                    request,
                    _("When Windy start camera is 1000, only 1 block is available on this API tier."),
                )
                return redirect("scraping:job_list")

        if source not in {"INSECAM", "WHATSUPCAMS", "WINDY"}:
            logger.warning("Invalid scrape source submitted by user=%s: %s", request.user, source)
            messages.error(request, _("Choose a valid scrape source."))
            return redirect("scraping:job_list")

        if source == "INSECAM" and not target_country_code:
            messages.error(request, _("Choose a country for Insecam scrape."))
            return redirect("scraping:job_list")

        if source == "INSECAM" and not is_allowed_insecam_country(target_country_code):
            messages.error(
                request,
                _("Country '%(country)s' is not enabled in INSECAM_COUNTRY_CODES config.")
                % {"country": target_country_code},
            )
            return redirect("scraping:job_list")

        if source == "WHATSUPCAMS" and target_country_code and not is_allowed_whatsupcams_country(target_country_code):
            messages.error(
                request,
                _("Country '%(country)s' is not enabled in WHATSUPCAMS_COUNTRY_CODES config.")
                % {"country": target_country_code},
            )
            return redirect("scraping:job_list")

        active_filters = {
            "source_type": source,
            "status__in": [ScrapeJobStatus.PENDING, ScrapeJobStatus.RUNNING],
            "target_country_code": target_country_code,
        }

        active_job = ScrapeJob.objects.filter(**active_filters).order_by("-created_at").first()
        if active_job:
            target_suffix = f" ({active_job.target_country_code})" if active_job.target_country_code else ""
            messages.warning(
                request,
                _("%(source)s%(suffix)s already has an active job (#%(job_id)s, %(status)s).")
                % {
                    "source": source,
                    "suffix": target_suffix,
                    "job_id": active_job.pk,
                    "status": active_job.status,
                },
            )
            return redirect("scraping:job_list")

        # Temporarily disabled cooldown blocking to allow repeated manual triggering.
        # Keep active job protection above to avoid duplicate concurrent runs.

        if not self._has_online_workers():
            messages.error(request, _("No Celery workers are online. Start a worker and try again."))
            return redirect("scraping:job_list")

        if source == "INSECAM":
            from apps.scraping.tasks import scrape_insecam_job

            job = ScrapeJob.objects.create(
                source_type=source,
                target_country_code=target_country_code,
            )
            try:
                task = scrape_insecam_job.delay(job_id=job.pk)
            except Exception as exc:
                job.mark_failed(error=f"Queue enqueue failed: {exc}")
                logger.exception("Failed to enqueue Insecam scrape job #%s: %s", job.pk, exc)
                messages.error(request, _("Failed to enqueue Insecam scrape. Check broker/worker status."))
                return redirect("scraping:job_list")

            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id"])
            logger.info(
                "Triggered Insecam scrape: task_id=%s country=%s job_id=%s by user=%s",
                task.id,
                target_country_code,
                job.pk,
                request.user,
            )
            messages.success(
                request,
                _("Insecam [%(country)s] scrape queued (job #%(job_id)s): %(task_id)s")
                % {"country": target_country_code, "job_id": job.pk, "task_id": task.id},
            )
        elif source == "WHATSUPCAMS":
            from apps.scraping.tasks import scrape_whatsupcams_job

            job = ScrapeJob.objects.create(source_type=source, target_country_code=target_country_code)
            try:
                task = scrape_whatsupcams_job.delay(job_id=job.pk)
            except Exception as exc:
                job.mark_failed(error=f"Queue enqueue failed: {exc}")
                logger.exception("Failed to enqueue WhatsUpCams scrape job #%s: %s", job.pk, exc)
                messages.error(request, _("Failed to enqueue WhatsUpCams scrape. Check broker/worker status."))
                return redirect("scraping:job_list")

            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id"])
            logger.info(
                "Triggered WUC scrape: task_id=%s country=%s job_id=%s by user=%s",
                task.id,
                target_country_code or "ALL",
                job.pk,
                request.user,
            )
            scope = f"[{target_country_code}] " if target_country_code else ""
            messages.success(
                request,
                _("WhatsUpCams %(scope)sscrape queued (job #%(job_id)s): %(task_id)s")
                % {"scope": scope, "job_id": job.pk, "task_id": task.id},
            )
        elif source == "WINDY":
            from apps.scraping.tasks import scrape_windy_job

            job = ScrapeJob.objects.create(
                source_type=source,
                target_country_code=target_country_code,
                offset_pages=windy_start_camera // 1000,
                max_pages=windy_block_count * 20,
            )
            try:
                task = scrape_windy_job.delay(job_id=job.pk)
            except Exception as exc:
                job.mark_failed(error=f"Queue enqueue failed: {exc}")
                logger.exception("Failed to enqueue Windy scrape job #%s: %s", job.pk, exc)
                messages.error(request, _("Failed to enqueue Windy scrape. Check broker/worker status."))
                return redirect("scraping:job_list")

            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id"])
            logger.info(
                "Triggered Windy scrape: task_id=%s country=%s job_id=%s by user=%s",
                task.id,
                target_country_code or "ALL",
                job.pk,
                request.user,
            )
            scope = f"[{target_country_code}] " if target_country_code else ""
            messages.success(
                request,
                _("Windy %(scope)s scrape queued from %(start)s (job #%(job_id)s): %(task_id)s")
                % {
                    "scope": scope,
                    "start": windy_start_camera,
                    "job_id": job.pk,
                    "task_id": task.id,
                },
            )
        return redirect("scraping:job_list")


class CancelScrapeView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        job = get_object_or_404(ScrapeJob, pk=pk)

        if job.is_terminal:
            messages.info(
                request,
                _("Job #%(job_id)s is already %(status)s.") % {"job_id": job.pk, "status": job.status},
            )
            return redirect("scraping:job_list")

        if job.celery_task_id:
            from celery.result import AsyncResult

            AsyncResult(job.celery_task_id).revoke(terminate=True, signal="SIGTERM")

        job.mark_cancelled(reason=f"Cancelled by {request.user}")
        logger.info("Cancelled scrape job #%s by user=%s", job.pk, request.user)
        messages.success(request, _("Cancelled scrape job #%(job_id)s.") % {"job_id": job.pk})
        return redirect("scraping:job_list")


# ── HTMX partials ────────────────────────────────────────────────────────────

class HtmxJobListView(LoginRequiredMixin, ListView):
    model = ScrapeJob
    template_name = "htmx/scraping/_job_row.html"
    context_object_name = "jobs"

    def get_queryset(self):
        qs = ScrapeJob.objects.all()
        if source := self.request.GET.get("source"):
            qs = qs.filter(source_type=source)
        if status := self.request.GET.get("status"):
            qs = qs.filter(status=status)
        return qs[:20]


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


