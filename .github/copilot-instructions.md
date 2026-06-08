# COPILOT INSTRUCTIONS FOR RECONEYE (PRODUCTION FINAL)

## PROJECT CONTEXT & ARCHITECTURE
- **Core Stack:** Python 3.12+, Django 5+, HTMX, Bootstrap 5, PostgreSQL, Redis, Celery.
- **Project Goal:** Build a production-ready, server-rendered Django app for ReconEye, using branch `wuc` as the reference for WhatsUpCams behavior.
- **Simplicity First:** The system prioritizes simplicity, maintainability, and minimal complexity. Avoid overengineering and unnecessary abstractions.
- **Strict No-SPA Policy:** Server-rendered Django application only. Use HTMX for all UI interactivity. Absolutely NO SPA frameworks (`React`, `Vue`, `Angular`). Render HTML on the server and return partial templates for HTMX.
- **Project Layout:** 
  `config/`, `apps/{cameras,scraping,dashboard,users,common}/`, `templates/`, `static/`, `media/`, `requirements/`, `docker/`, `scripts/`.
- **Engineering Principles:** Prefer class-based views, typed Python (`type hints`), modular code, and Django best practices. Prefer minimal and incremental changes. Reuse existing code, utilities, and patterns.

---

## COOPILOT ACTION & OUTPUT RULES (LOW TOKEN MODE)
- **Code Style:** Prefer direct implementation over explanation. Do not describe what could be done; implement it. Keep responses minimal and focused. Do not propose multiple solutions unless explicitly requested.
- **Output Format:** Return only minimal diffs. Never output full files. Show only modified functions, blocks, or lines. Use comments like `# ... existing code ...` or `<!-- ... existing code ... -->` for unchanged parts. No explanations unless explicitly requested.
- **Context Handling:** Use only relevant local context (current file preferred). Do not assume unseen codebase structure. If required context or clarity is missing, ask a short question instead of guessing.

---

## HTMX & UI RULES
- **UI Behavior:** Prefer HTMX over JavaScript for UI behavior. Use server-rendered HTML responses instead of API + frontend state. Avoid client-side state management. Use minimal JavaScript only when strictly necessary.
- **Pages:** Dashboard, cameras list/detail, scrape jobs, stats, login. UI must be responsive, minimal, and dark-mode friendly.
- **HTMX Endpoints:** Implement endpoints returning HTML partials (e.g., `/htmx/cameras/`, `/htmx/jobs/`, `/htmx/dashboard-stats/`). Standard HTMX targets: camera list container, job table body, dashboard stats cards.
- **URL Namespaces:** Use URL namespaces by app: `cameras:htmx_list`, `scraping:htmx_jobs`, `dashboard:htmx_stats`.
- **Template Conventions:** Keep HTMX partials in `templates/htmx/<domain>/` and prefix reusable fragments with `_` (e.g., `_job_row.html`, `_camera_table.html`). Full-page templates compose partials; HTMX endpoints return partials only (no duplicated page shell).
- **Polling:** Use HTMX polling for job status (progress, state, start, duration, processed count, errors) with no full-page reload.

---

## CORE DOMAIN MODELS & DATA STATE
- **Camera:** Include metadata, location, source, URLs, online/active flags, timestamps. Index fields: `country`, `city`, `source_type`, `is_online`.
- **Diagnostics:** `Camera` must include `has_partial_metadata: bool` and `source_payload: JSONField` (`default=dict`, never null) for parser diagnostics and traceability.
- **SourceType Options:** `INSECAM`, `WHATSUPCAMS`.
- **ScrapeJob:** Lifecycle/status tracking (`PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `CANCELLED`) + counters + error + `celery_task_id`.
- **CameraCheckLog:** Status checks with retention cleanup task.
- **Partial-Camera State Data Convention:** Standardize behavior for missing direct streams:
  - `stream_url` empty/null, `page_url` required, camera remains persisted.
  - Set `has_partial_metadata=True` whenever a direct playable stream cannot be extracted.
  - Never mark a camera offline only because a direct stream URL is unavailable; online status is check-task driven.

---

## CELERY & BACKGROUND PROCESSING
- **Execution:** Never run scraping in the request thread or ad-hoc threading; always use Celery workers + Redis broker. Business logic lives in `apps/<app>/services.py`; tasks call services, services do not import tasks.
- **Module Layout:** Task modules live at `apps/<app>/tasks.py`. Import only lightweight helpers—never import Django ORM models at module load time outside of the task body.
- **Required Tasks:** `scrape_insecam`, `scrape_whatsupcams`, `refresh_camera_status`, `cleanup_old_logs`, `warm_cache`.
- **Scraping Implementation:** Use `httpx` + `asyncio` + `aiolimiter` (not `requests`), with retry/timeout/rate limiting/deduplication. Keep scraping logic in a service layer and reusable components; avoid duplicating source-specific parsers.
- **Parser Location:** Scraper parsers/HTTP helpers live in `apps/scraping/parsers/<source>.py` (e.g., `insecam.py`, `whatsupcams.py`). Shared HTTP client setup and rate-limiter factory live in `apps/scraping/http.py`.
- **Task Configurations:** Naming convention (Celery `name=`): `reconeye.<app>.<task_name>`. All tasks must use `bind=True`, `max_retries`, and `autoretry_for` where applicable.
- **Schedules:** Periodic task schedule is defined in `config/celery.py` under `app.conf.beat_schedule`, not in individual app files.
- **WhatsUpCams Spec:** Preserve `wuc` branch logic. If the direct stream is missing, store `page_url` and mark as partial metadata.

---

## PROGRESS TRACKING CONTRACT
- **Counters:** Track progress from persisted counters only: `total_found`, `total_processed`, `total_new`, `total_updated`.
- **Formula:** Compute progress as: `progress_pct = min(100, round((total_processed / max(total_found, 1)) * 100))`.
- **Timestamps:** Set `started_at` when a job transitions to `RUNNING`; set `finished_at` only on terminal states (`SUCCESS`, `FAILED`, `CANCELLED`).
- **UI Sync:** HTMX job rows/cards must render the exact same progress formula as the backend to avoid UI drift.

---

## CACHING & PERFORMANCE
- **Strategy:** Use Redis cache backend aggressively (camera lists, filters, dashboard stats, scrape summaries) via low-level cache API + fragment caching + timeout strategy. Support admin/manual cache invalidation and automatic invalidation on relevant writes.
- **Database Optimization:** Optimize ORM and writes with pagination, `select_related`, `prefetch_related`, `bulk_create`, `bulk_update`, and proper DB indexes.
- **Cache Key Design:** Use versioned keys: `reconeye:v1:<domain>:<scope>` (e.g., `reconeye:v1:cameras:list:country=hr:page=2`). Keep domain prefixes: `cameras`, `dashboard`, `scrape_jobs`, `filters`, `stats`.
- **TTL Policy:**
  - Camera list/filter keys: 120s
  - Dashboard/stats keys: 60s
  - Scrape job summary keys: 30s
  - Warm-cache precomputed keys: 300s
- **Invalidation Rules:**
  - `Camera` write/delete -> invalidate `cameras`, `filters`, `dashboard`, `stats`.
  - `ScrapeJob` write/delete -> invalidate `scrape_jobs`, `dashboard`, `stats`.
  - `CameraCheckLog` inserts -> invalidate `dashboard`, `stats` only.
- **Required Admin Actions:** `invalidate_cameras_cache`, `invalidate_dashboard_cache`, `invalidate_scrape_jobs_cache`, `invalidate_all_cache`.

---

## SECURITY & DEV OOPS
- **Access Control:** Entire app requires login except: login, logout, health/readiness endpoints. Django admin is staff-only.
- **Security Protocols:** Use Django session auth + CSRF, secure cookies, secure headers, input validation, XSS-safe rendering.
- **Container Stack:** `django`, `postgres`, `redis`, `celery_worker`, `celery_beat`, `nginx`. Production setup: `gunicorn`, `whitenoise`, env-driven config, structured logging.
- **Observability:** Log scrape failures, task execution, cache misses, login attempts, and performance warnings.
- **Tooling:** `uv` or `poetry`, `ruff`, `black`, `mypy`, `pre-commit`, `pytest`, `pytest-django`.

---

## DELIVERY PRIORITY
1. Django setup | 2. Auth/login | 3. Models | 4. Admin | 5. Redis + Celery | 6. Insecam scraper | 7. WhatsUpCams scraper | 8. HTMX UI | 9. Dashboard | 10. Cache optimizations | 11. Docker | 12. Tests