from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.cameras.models import Go2RTCGridProfile
from apps.common.authz import ROLE_OPERATOR
from apps.common.models import AuditLog


def _user(*, username: str):
    user_model = get_user_model()
    return user_model.objects.create_user(username=username, password="test-pass-123")


def test_viewer_cannot_create_go2rtc_profile(client, db) -> None:
    profile_name = "Viewer Forbidden Wall"
    user = _user(username="viewer")
    client.force_login(user)

    response = client.post(
        reverse("cameras:go2rtc_profile_add"),
        {"name": profile_name, "description": "Primary wall"},
    )

    assert response.status_code == 403
    assert Go2RTCGridProfile.objects.filter(name=profile_name).count() == 0
    assert AuditLog.objects.count() == 0


def test_operator_can_create_go2rtc_profile_and_audit_is_recorded(client, db) -> None:
    user = _user(username="operator")
    operator_group, _ = Group.objects.get_or_create(name=ROLE_OPERATOR)
    user.groups.add(operator_group)
    client.force_login(user)

    response = client.post(
        reverse("cameras:go2rtc_profile_add"),
        {"name": "Ops Wall", "description": "Primary wall"},
    )

    assert response.status_code == 302
    profile = Go2RTCGridProfile.objects.get(name="Ops Wall")
    audit = AuditLog.objects.get(action="create")
    assert audit.actor == user
    assert audit.object_id == str(profile.pk)
    assert audit.after_state["description"] == "Primary wall"