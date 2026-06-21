from django.test import override_settings
from django.urls import reverse

from apps.common.capabilities import CAP_DYNAMIC_DASHBOARD_SOURCES, CAP_GO2RTC_MANAGER, is_capability_enabled
from apps.users.models import User


def test_capabilities_are_enabled_by_default() -> None:
    assert is_capability_enabled(CAP_DYNAMIC_DASHBOARD_SOURCES) is True
    assert is_capability_enabled(CAP_GO2RTC_MANAGER) is True


@override_settings(RECON_EYE_CAPABILITIES={"go2rtc_manager": False})
def test_capability_can_be_disabled_via_settings() -> None:
    assert is_capability_enabled(CAP_GO2RTC_MANAGER) is False


@override_settings(RECON_EYE_CAPABILITIES={"go2rtc_manager": False})
def test_disabled_go2rtc_capability_hides_route(client, db) -> None:
    user = User.objects.create_user(username="cap-user", password="pw")
    client.force_login(user)

    response = client.get(reverse("cameras:go2rtc_manager"))

    assert response.status_code == 404


@override_settings(RECON_EYE_CAPABILITIES={"go2rtc_manager": False})
def test_disabled_go2rtc_capability_hides_viewer_route(client, db) -> None:
    user = User.objects.create_user(username="cap-viewer-user", password="pw")
    client.force_login(user)

    response = client.get(reverse("cameras:go2rtc_viewer"))

    assert response.status_code == 404