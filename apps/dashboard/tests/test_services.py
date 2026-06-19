from django.template.loader import render_to_string

from apps.cameras.models import Camera, SourceType
from apps.dashboard.services import get_dashboard_stats


def test_get_dashboard_stats_returns_dynamic_source_counts(db) -> None:
    Camera.objects.create(source_type=SourceType.INSECAM, is_active=True, is_online=True)
    Camera.objects.create(source_type=SourceType.WINDY, is_active=True, is_online=False)
    Camera.objects.create(source_type=SourceType.GO2RTC, is_active=True, is_online=True)
    Camera.objects.create(source_type=SourceType.GO2RTC, is_active=True, is_online=False)
    Camera.objects.create(source_type=SourceType.WHATSUPCAMS, is_active=False, is_online=True)

    stats = get_dashboard_stats(force=True)

    assert stats["total"] == 4
    assert stats["online"] == 2
    assert stats["offline"] == 2
    assert stats["by_source"] == [
        {"source_type": SourceType.GO2RTC, "label": "go2rtc", "count": 2},
        {"source_type": SourceType.INSECAM, "label": "Insecam", "count": 1},
        {"source_type": SourceType.WINDY, "label": "Windy", "count": 1},
    ]


def test_dashboard_stats_partial_renders_sources_without_countries(db) -> None:
    Camera.objects.create(source_type=SourceType.WINDY, is_active=True, is_online=True)

    html = render_to_string(
        "htmx/dashboard/_stats.html",
        {"stats": get_dashboard_stats(force=True)},
    )

    assert "By Source" in html
    assert "Windy" in html
    assert "Top Countries" not in html