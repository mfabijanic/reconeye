from django.test import override_settings
from django.urls import reverse

from apps.users.models import User


def test_dashboard_renders_sidebar_for_authenticated_user(client, db) -> None:
    user = User.objects.create_user(username="dash-user", password="pw")
    client.force_login(user)

    response = client.get(reverse("dashboard:index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'id="appSidebar"' in content
    assert "Scrape Jobs" in content


@override_settings(RECON_EYE_CAPABILITIES={"go2rtc_manager": False})
def test_dashboard_hides_disabled_go2rtc_navigation(client, db) -> None:
    user = User.objects.create_user(username="dash-cap-user", password="pw")
    client.force_login(user)

    response = client.get(reverse("dashboard:index"))

    assert response.status_code == 200
    assert "go2rtc Manager" not in response.content.decode()
