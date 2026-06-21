from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.cameras.models import Go2RTCInstance


def _user(*, username: str):
    user_model = get_user_model()
    return user_model.objects.create_user(username=username, password="test-pass-123")


def _instance() -> Go2RTCInstance:
    return Go2RTCInstance.objects.create(
        name="Private go2rtc",
        scheme="http",
        host="go2rtc.local",
        port=1984,
        is_active=True,
        is_private=True,
    )


def test_surveillance_page_hides_open_manager_button(client, db) -> None:
    user = _user(username="surveillance-ui-user")
    client.force_login(user)

    response = client.get(reverse("cameras:surveillance"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Open Manager" not in content
    assert "cameras" in content


def test_surveillance_server_health_shows_offline_badge(client, db) -> None:
    user = _user(username="surveillance-health-offline")
    _instance()
    client.force_login(user)

    with patch("apps.cameras.views.fetch_go2rtc_streams", return_value=([], "Unable to fetch the stream list from: http://go2rtc.local:1984/api/streams")) as mocked_fetch:
        response = client.get(reverse("cameras_htmx:surveillance_server_health"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Offline" in content
    assert "bi-exclamation-octagon-fill" in content
    mocked_fetch.assert_called_once_with(
        base_url="http://go2rtc.local:1984",
        timeout_seconds=1.5,
        use_cache=False,
    )


def test_surveillance_server_health_hides_offline_badge_when_online(client, db) -> None:
    user = _user(username="surveillance-health-online")
    _instance()
    client.force_login(user)

    with patch("apps.cameras.views.fetch_go2rtc_streams", return_value=([{"name": "cam-1", "producers": 1, "consumers": 0}], None)):
        response = client.get(reverse("cameras_htmx:surveillance_server_health"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "http://go2rtc.local:1984" in content
    assert "Offline" not in content
    assert "bi-exclamation-octagon-fill" not in content