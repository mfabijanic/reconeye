from django.contrib.auth import get_user_model
from django.urls import reverse


def _user(*, username: str):
    user_model = get_user_model()
    return user_model.objects.create_user(username=username, password="test-pass-123")


def test_go2rtc_manager_hides_open_surveillance_button(client, db) -> None:
    user = _user(username="manager-ui-user")
    client.force_login(user)

    response = client.get(reverse("cameras:go2rtc_manager"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Open Surveillance Grid" not in content
    assert "Open Viewer" in content


def test_go2rtc_viewer_hides_open_surveillance_button(client, db) -> None:
    user = _user(username="viewer-ui-user")
    client.force_login(user)

    response = client.get(reverse("cameras:go2rtc_viewer"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Open Surveillance" not in content
    assert "Open Manager" in content
