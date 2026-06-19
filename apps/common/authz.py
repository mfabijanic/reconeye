from __future__ import annotations

from django.contrib.auth.mixins import AccessMixin
from django.http import Http404
from django.core.exceptions import PermissionDenied

from apps.common.capabilities import is_capability_enabled


ROLE_VIEWER = "viewer"
ROLE_OPERATOR = "operator"
ROLE_MANAGER = "manager"

ROLE_GROUPS = (ROLE_VIEWER, ROLE_OPERATOR, ROLE_MANAGER)


def user_has_role(user, *roles: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True
    if not roles:
        return False
    return user.groups.filter(name__in=roles).exists()


class RoleRequiredMixin(AccessMixin):
    required_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not user_has_role(request.user, *self.required_roles):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class CapabilityRequiredMixin(AccessMixin):
    required_capability: str | None = None

    def dispatch(self, request, *args, **kwargs):
        if self.required_capability and not is_capability_enabled(self.required_capability):
            raise Http404
        return super().dispatch(request, *args, **kwargs)