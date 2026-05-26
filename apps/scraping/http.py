"""
Shared async HTTP client and rate-limiter factory for all scrapers.

Usage:
    async with build_client() as client:
        resp = await client.get(url)
"""
from __future__ import annotations

import random

import httpx
from aiolimiter import AsyncLimiter

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# Rotate between realistic User-Agents to avoid detection
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/124.0",
]

DEFAULT_HEADERS = {
    "User-Agent": random.choice(USER_AGENTS),
    "Accept-Language": "en-US,en;q=0.9",
}

# Global rate limiter: 1 request/second (respectful, avoids "hammering")
_global_limiter = AsyncLimiter(max_rate=1, time_period=1)


def get_limiter(max_rate: float = 1, time_period: float = 1) -> AsyncLimiter:
    """Create a rate limiter. Default: 1 req/sec (respectful scraping)."""
    return AsyncLimiter(max_rate=max_rate, time_period=time_period)


def build_client(
    *,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    headers: dict | None = None,
    follow_redirects: bool = True,
    http2: bool = True,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        headers={**DEFAULT_HEADERS, **(headers or {})},
        follow_redirects=follow_redirects,
        http2=http2,
    )
