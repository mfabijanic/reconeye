from django.contrib.auth.models import Group
from django.test import RequestFactory

from apps.common.audit import log_audit_event
from apps.common.authz import ROLE_OPERATOR, user_has_role
from apps.common.models import AuditLog
from apps.users.models import User


def test_user_has_role_via_group(db) -> None:
    group, _ = Group.objects.get_or_create(name=ROLE_OPERATOR)
    user = User.objects.create_user(username="operator", password="pw")
    user.groups.add(group)

    assert user_has_role(user, ROLE_OPERATOR) is True


def test_audit_log_persists_request_context(db) -> None:
    user = User.objects.create_user(username="auditor", password="pw")
    request = RequestFactory().post("/scraping/jobs/trigger/", HTTP_USER_AGENT="pytest-agent")
    request.user = user
    request.META["REMOTE_ADDR"] = "127.0.0.1"

    entry = log_audit_event(
        request=request,
        action=AuditLog.Action.EXECUTE,
        target_label="manual test",
        before_state={"status": "before"},
        after_state={"status": "after"},
        metadata={"operation": "unit_test"},
    )

    stored = AuditLog.objects.get(pk=entry.pk)
    assert stored.actor == user
    assert stored.route == "/scraping/jobs/trigger/"
    assert stored.ip_address == "127.0.0.1"
    assert stored.user_agent == "pytest-agent"
    assert stored.before_state == {"status": "before"}
    assert stored.after_state == {"status": "after"}
    assert stored.metadata == {"operation": "unit_test"}