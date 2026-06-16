"""
Services for Go2RTCGridItem (Surveillance domain).

Handles creation, update, and removal of surveillance grid items.
Provides adapter to map grid items to camera-like objects for template compatibility.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import transaction

from apps.cameras.models import (
    Go2RTCGridItem,
    Go2RTCGridProfile,
    Go2RTCInstance,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class GridItemAdapter:
    """
    Adapter to expose Go2RTCGridItem as a camera-like object for templates.
    Template expects objects with: pk, title, stream_url, etc.
    This adapter maps grid item + instance data to those fields.
    """

    def __init__(self, grid_item: Go2RTCGridItem, stream_urls: dict[str, str] | None = None):
        self.grid_item = grid_item
        self.instance = grid_item.instance
        self.stream_urls = stream_urls or {}

    @property
    def pk(self) -> int:
        """Return grid_item.pk so HTMX player route can use it."""
        return self.grid_item.pk

    @property
    def id(self) -> int:
        """Return grid_item.id for template iteration."""
        return self.grid_item.id

    @property
    def title(self) -> str:
        """Return grid_item.title or stream_name as fallback."""
        return self.grid_item.title or self.grid_item.stream_name

    @property
    def stream_url(self) -> str:
        """Return WebRTC embed URL for this stream."""
        return self.stream_urls.get("webrtc_embed", "")

    @property
    def page_url(self) -> str:
        """Return page URL (for manual access)."""
        return self.stream_urls.get("webrtc_embed", "")

    @property
    def source_type(self) -> str:
        return "GO2RTC"

    @property
    def source_payload(self) -> dict:
        """Provide stream_urls in source_payload to match Camera template expectations."""
        return {"stream_urls": self.stream_urls}

    @property
    def is_active(self) -> bool:
        return self.grid_item.is_active

    def __str__(self) -> str:
        return f"{self.title} ({self.instance.host}:{self.instance.port})"

    def __repr__(self) -> str:
        return f"<GridItemAdapter pk={self.pk} title={self.title}>"


def get_surveillance_profile() -> Go2RTCGridProfile:
    """Get or create the default 'surveillance' profile."""
    profile, _ = Go2RTCGridProfile.objects.get_or_create(
        name="surveillance",
        defaults={
            "description": "Private surveillance grid (system default)",
            "is_active": True,
        },
    )
    return profile


def get_or_create_default_private_instance() -> Go2RTCInstance:
    """
    Get first active private instance, or create a default one.
    Used when adding cameras to surveillance grid without explicit instance selection.
    """
    # Try to find existing private instance
    existing = Go2RTCInstance.objects.filter(
        is_active=True,
        is_private=True,
    ).first()
    if existing:
        return existing

    # Fall back: create a placeholder private instance
    # This should rarely happen; normally user provides one via import or admin
    instance, _ = Go2RTCInstance.objects.get_or_create(
        host="localhost",
        port=1984,
        defaults={
            "base_url": "http://localhost:1984",
            "is_active": True,
            "is_private": True,
            "last_synced_at": None,
        },
    )
    logger.warning(
        f"Created default localhost private go2rtc instance: {instance.base_url}"
    )
    return instance


@transaction.atomic
def upsert_go2rtc_grid_item(
    *,
    instance: Go2RTCInstance,
    stream_name: str,
    title: str = "",
    profile: Go2RTCGridProfile | None = None,
) -> tuple[Go2RTCGridItem, bool]:
    """
    Create or update a Go2RTCGridItem in the surveillance profile.

    Args:
        instance: Go2RTCInstance to link
        stream_name: Name of the stream in go2rtc
        title: Display title (optional, defaults to stream_name)
        profile: Grid profile (defaults to surveillance profile)

    Returns:
        (Go2RTCGridItem, created: bool)
    """
    if profile is None:
        profile = get_surveillance_profile()

    clean_stream_name = stream_name.strip()
    clean_title = title.strip() or clean_stream_name

    item, created = Go2RTCGridItem.objects.update_or_create(
        profile=profile,
        instance=instance,
        stream_name=clean_stream_name,
        defaults={
            "title": clean_title,
            "is_active": True,
            "source_payload": {
                "provider": "go2rtc",
                "base_url": instance.base_url,
                "stream_name": clean_stream_name,
            },
        },
    )
    logger.info(
        f"{'Created' if created else 'Updated'} grid item: {item.title} on {instance.host}"
    )
    return item, created


def remove_go2rtc_grid_item(grid_item: Go2RTCGridItem) -> None:
    """Soft-delete a grid item (mark as inactive)."""
    grid_item.is_active = False
    grid_item.save(update_fields=["is_active", "updated_at"])
    logger.info(f"Removed grid item: {grid_item.title}")


def get_surveillance_grid_items_with_adapters() -> list[GridItemAdapter]:
    """
    Fetch all active surveillance grid items with private instances.
    Map to GridItemAdapter for template compatibility.

    Returns:
        List of GridItemAdapter objects ready for template rendering
    """
    from apps.cameras.services import build_go2rtc_stream_urls

    profile = get_surveillance_profile()
    items = Go2RTCGridItem.objects.filter(
        profile=profile,
        is_active=True,
        instance__is_active=True,
        instance__is_private=True,
    ).select_related("instance").order_by("sort_order", "id")

    adapters = []
    for item in items:
        urls = build_go2rtc_stream_urls(item.instance.base_url, item.stream_name)
        adapter = GridItemAdapter(item, stream_urls=urls)
        adapters.append(adapter)

    return adapters
