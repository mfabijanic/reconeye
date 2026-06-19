from __future__ import annotations

from apps.common.capabilities import is_capability_enabled


def common_capabilities(request):
    return {
        "app_capabilities": {
            "dynamic_dashboard_sources": is_capability_enabled("dynamic_dashboard_sources"),
            "go2rtc_manager": is_capability_enabled("go2rtc_manager"),
            "advanced_audit": is_capability_enabled("advanced_audit"),
            "sidebar_navigation": is_capability_enabled("sidebar_navigation"),
            "surveillance": True,
        }
    }