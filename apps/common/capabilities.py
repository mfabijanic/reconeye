from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class Capability:
    key: str
    default_enabled: bool = True


CAP_DYNAMIC_DASHBOARD_SOURCES = Capability("dynamic_dashboard_sources")
CAP_GO2RTC_MANAGER = Capability("go2rtc_manager")
CAP_ADVANCED_AUDIT = Capability("advanced_audit")
CAP_SIDEBAR_NAVIGATION = Capability("sidebar_navigation")


def is_capability_enabled(capability: Capability | str) -> bool:
    key = capability.key if isinstance(capability, Capability) else capability
    defaults = {
        CAP_DYNAMIC_DASHBOARD_SOURCES.key: CAP_DYNAMIC_DASHBOARD_SOURCES.default_enabled,
        CAP_GO2RTC_MANAGER.key: CAP_GO2RTC_MANAGER.default_enabled,
        CAP_ADVANCED_AUDIT.key: CAP_ADVANCED_AUDIT.default_enabled,
        CAP_SIDEBAR_NAVIGATION.key: CAP_SIDEBAR_NAVIGATION.default_enabled,
    }
    configured = getattr(settings, "RECON_EYE_CAPABILITIES", {}) or {}
    return bool(configured.get(key, defaults.get(key, True)))