"""
Cache utility functions for ReconEye.

Key schema:  reconeye:v1:<domain>:<scope>
TTL policy:
  cameras list/filter keys  : 120s
  dashboard/stats keys      : 60s
  scrape job summary keys   : 30s
  warm-cache precomputed    : 300s
"""
from __future__ import annotations

from django.core.cache import cache

# ── TTLs ────────────────────────────────────────────────────────────────────
TTL_CAMERAS = 120
TTL_DASHBOARD = 60
TTL_SCRAPE_JOBS = 30
TTL_WARM = 300

# ── Key builders ────────────────────────────────────────────────────────────
DOMAIN_CAMERAS = "cameras"
DOMAIN_DASHBOARD = "dashboard"
DOMAIN_SCRAPE_JOBS = "scrape_jobs"
DOMAIN_FILTERS = "filters"
DOMAIN_STATS = "stats"
DOMAIN_GO2RTC = "go2rtc"


def make_key(domain: str, *parts: str | int) -> str:
    slug = ":".join(str(p) for p in parts)
    return f"v1:{domain}:{slug}"


# ── Invalidation ────────────────────────────────────────────────────────────
# We invalidate by cache key pattern using a simple version-bump strategy.
# Each domain has a version counter stored in cache; bump it to invalidate all
# keys that embed the version.  For simplicity we use delete_pattern via a
# sentinel key that stores the current generation.

def _gen_key(domain: str) -> str:
    return f"v1:gen:{domain}"


def get_generation(domain: str) -> int:
    return cache.get(_gen_key(domain), 0)


def bump_generation(domain: str) -> None:
    try:
        cache.incr(_gen_key(domain))
    except ValueError:
        cache.set(_gen_key(domain), 1, timeout=None)


def invalidate_cameras() -> None:
    bump_generation(DOMAIN_CAMERAS)
    bump_generation(DOMAIN_FILTERS)
    bump_generation(DOMAIN_STATS)
    bump_generation(DOMAIN_DASHBOARD)


def invalidate_dashboard() -> None:
    bump_generation(DOMAIN_DASHBOARD)
    bump_generation(DOMAIN_STATS)


def invalidate_scrape_jobs() -> None:
    bump_generation(DOMAIN_SCRAPE_JOBS)
    bump_generation(DOMAIN_DASHBOARD)
    bump_generation(DOMAIN_STATS)


def invalidate_all() -> None:
    for domain in [
        DOMAIN_CAMERAS,
        DOMAIN_DASHBOARD,
        DOMAIN_SCRAPE_JOBS,
        DOMAIN_FILTERS,
        DOMAIN_STATS,
        DOMAIN_GO2RTC,
    ]:
        bump_generation(domain)


def invalidate_go2rtc() -> None:
    bump_generation(DOMAIN_GO2RTC)
    bump_generation(DOMAIN_FILTERS)
    bump_generation(DOMAIN_DASHBOARD)
    bump_generation(DOMAIN_STATS)


def versioned_key(domain: str, *parts: str | int) -> str:
    """Return a cache key that includes the current domain generation."""
    gen = get_generation(domain)
    return make_key(domain, f"g{gen}", *parts)
