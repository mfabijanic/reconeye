from django.contrib.auth.models import Group
from django.urls import reverse

from apps.common.authz import ROLE_OPERATOR
from apps.users.models import User


def test_trigger_scrape_requires_operator_role(client, db) -> None:
    user = User.objects.create_user(username="viewer", password="pw")
    client.force_login(user)

    response = client.post(reverse("scraping:trigger"), {"source_type": "INSECAM", "country_code": "HR"})

    assert response.status_code == 403


def test_trigger_scrape_allows_operator_before_business_validation(client, db) -> None:
    group, _ = Group.objects.get_or_create(name=ROLE_OPERATOR)
    user = User.objects.create_user(username="operator", password="pw")
    user.groups.add(group)
    client.force_login(user)

    response = client.post(reverse("scraping:trigger"), {"source_type": "INVALID"})

    assert response.status_code == 302