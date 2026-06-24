from django.contrib.auth import get_user_model
from django.urls import reverse


def test_camera_map_page_contains_latitude_attribute_for_location_suggestions(client, db) -> None:
    user_model = get_user_model()
    user = user_model.objects.create_user(username="map-test-user", password="test-pass-123")
    client.force_login(user)

    response = client.get(reverse("cameras:map"))

    assert response.status_code == 200
    assert "data-lat=" in response.content.decode()


def test_camera_map_page_includes_fullscreen_css_rules(client, db) -> None:
    user_model = get_user_model()
    user = user_model.objects.create_user(username="map-fullscreen-test-user", password="test-pass-123")
    client.force_login(user)

    response = client.get(reverse("cameras:map"))

    assert response.status_code == 200
    content = response.content.decode()
    assert ".stream-player:fullscreen" in content
    assert "width: 100vw !important;" in content
    assert "height: 100vh !important;" in content
