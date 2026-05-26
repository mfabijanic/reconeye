# Copilot Instructions for ReconEye

## Project goal and reference
- Build a production-ready, server-rendered Django app for ReconEye, using branch `wuc` as the reference for WhatsUpCams behavior.
- Target stack: Python 3.12+, Django 5+, HTMX, Bootstrap 5, PostgreSQL, Redis, Celery.
- Do not introduce SPA frameworks (`React`, `Vue`); render HTML on server and return partial templates for HTMX.

## Required architecture
- Use project layout: `config/`, `apps/{cameras,scraping,dashboard,users,common}/`, `templates/`, `static/`, `media/`, `requirements/`, `docker/`, `scripts/`.
- Keep scraping logic in a service layer and reusable helper/repository components; avoid duplicating source-specific parsers.
- Prefer class-based views, typed Python (`type hints`), modular code, and Django best practices.

## Security and access control
- Entire app requires login except: login, logout, health/readiness endpoints.
- Use Django session auth + CSRF, secure cookies, secure headers, input validation, XSS-safe rendering.
- Django admin is staff-only.

## Core domain models
- `Camera`: include metadata, location, source, URLs, online/active flags, timestamps; index `country`, `city`, `source_type`, `is_online`.
- `Camera` must include `has_partial_metadata: bool` and `source_payload: JSONField` (`default=dict`, never null) for parser diagnostics.
- `SourceType`: `INSECAM`, `WHATSUPCAMS`.
- `ScrapeJob`: lifecycle/status tracking (`PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `CANCELLED`) + counters + error + `celery_task_id`.
- `CameraCheckLog`: status checks with retention cleanup task.

## Data-state conventions
- Standardize partial-camera state for missing direct stream:
	- `stream_url` empty/null, `page_url` required, camera remains persisted.
	- Set `has_partial_metadata=True` whenever direct playable stream cannot be extracted.
	- Never mark camera offline only because direct stream URL is unavailable; online status is check-task driven.
- `source_payload` is mandatory normalized scrape JSON (non-null, default `{}`) for parser debugging and traceability.

## Scraping and background processing
- Never run scraping in request thread or ad-hoc threading; always use Celery workers + Redis broker.
- Required tasks: `scrape_insecam`, `scrape_whatsupcams`, `refresh_camera_status`, `cleanup_old_logs`, `warm_cache`.
- Scraping implementation must use `httpx` + `asyncio` + `aiolimiter` (not `requests`), with retry/timeout/rate limiting/deduplication.
- For WhatsUpCams, preserve `wuc` branch logic; if direct stream missing, store `page_url` and mark as partial metadata.

## Celery task and service module layout
- Task modules live at `apps/<app>/tasks.py`; import only lightweight helpers — never import Django ORM models at module load time outside of task body.
- Business logic lives in `apps/<app>/services.py`; tasks call services, services do not import tasks.
- Scraper parsers/HTTP helpers live in `apps/scraping/parsers/<source>.py` (e.g. `insecam.py`, `whatsupcams.py`).
- Shared HTTP client setup and rate-limiter factory live in `apps/scraping/http.py`.
- Task naming convention (Celery `name=`): `reconeye.<app>.<task_name>` (e.g. `reconeye.scraping.scrape_insecam`).
- All tasks must use `bind=True`, `max_retries`, and `autoretry_for` where applicable.
- Periodic task schedule is defined in `config/celery.py` under `app.conf.beat_schedule`, not in individual app files.

## UI and HTMX behavior
- Pages: dashboard, cameras list/detail, scrape jobs, stats, login.
- Implement HTMX endpoints returning HTML partials (e.g. `/htmx/cameras/`, `/htmx/jobs/`, `/htmx/dashboard-stats/`).
- Use HTMX polling for job status (progress, state, start, duration, processed count, errors) with no full-page reload.
- UI must be responsive, minimal, and dark-mode friendly.

## Scrape progress contract
- Track progress from persisted counters only: `total_found`, `total_processed`, `total_new`, `total_updated`.
- Compute progress as: `progress_pct = min(100, round((total_processed / max(total_found, 1)) * 100))`.
- Set `started_at` when job transitions to `RUNNING`; set `finished_at` only on terminal states (`SUCCESS`, `FAILED`, `CANCELLED`).
- HTMX job rows/cards must render the same progress formula as backend to avoid UI drift.

## HTMX endpoint and template conventions
- Use URL namespaces by app: `cameras:htmx_list`, `scraping:htmx_jobs`, `dashboard:htmx_stats`.
- Keep HTMX partials in `templates/htmx/<domain>/` and prefix reusable fragments with `_` (example: `_job_row.html`, `_camera_table.html`).
- Full-page templates compose partials; HTMX endpoints return partials only (no duplicated page shell).
- Standard HTMX targets: camera list container, job table body, dashboard stats cards.

## Caching and performance
- Use Redis cache backend aggressively: camera lists, filters, dashboard stats, scrape summaries.
- Use low-level cache API + fragment caching + timeout strategy.
- Support admin/manual cache invalidation and automatic invalidation on relevant writes.
- Optimize ORM and writes with pagination, `select_related`, `prefetch_related`, `bulk_create`, `bulk_update`, and proper DB indexes.

## Cache key and invalidation rules
- Use versioned keys: `reconeye:v1:<domain>:<scope>` (example: `reconeye:v1:cameras:list:country=hr:page=2`).
- Keep domain prefixes: `cameras`, `dashboard`, `scrape_jobs`, `filters`, `stats`.
- Default TTL policy:
	- camera list/filter keys: 120s
	- dashboard/stats keys: 60s
	- scrape job summary keys: 30s
	- warm-cache precomputed keys: 300s
- Invalidate on model changes:
	- `Camera` write/delete -> invalidate `cameras`, `filters`, `dashboard`, `stats`.
	- `ScrapeJob` write/delete -> invalidate `scrape_jobs`, `dashboard`, `stats`.
	- `CameraCheckLog` inserts -> invalidate `dashboard`, `stats` only.
- Admin actions must exist with these names: `invalidate_cameras_cache`, `invalidate_dashboard_cache`, `invalidate_scrape_jobs_cache`, `invalidate_all_cache`.

## DevOps, observability, quality
- Container stack required: `django`, `postgres`, `redis`, `celery_worker`, `celery_beat`, `nginx`.
- Production setup: `gunicorn`, `whitenoise`, env-driven config, structured logging.
- Log scrape failures, task execution, cache misses, login attempts, and performance warnings.
- Tooling: `uv` or `poetry`, `ruff`, `black`, `mypy`, `pre-commit`, `pytest`, `pytest-django`.

## Delivery priority
1. Django setup
2. Auth/login
3. Models
4. Admin
5. Redis + Celery
6. Insecam scraper
7. WhatsUpCams scraper
8. HTMX UI
9. Dashboard
10. Cache optimizations
11. Docker
12. Tests
