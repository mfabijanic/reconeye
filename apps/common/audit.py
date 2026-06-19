from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType

from apps.common.models import AuditLog


def _request_ip(request) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def log_audit_event(
    *,
    request,
    action: str,
    target: object | None = None,
    target_label: str = "",
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    content_type = None
    object_id = ""
    derived_label = target_label
    if target is not None:
        content_type = ContentType.objects.get_for_model(target.__class__)
        object_id = str(getattr(target, "pk", "") or "")
        if not derived_label:
            derived_label = str(target)

    return AuditLog.objects.create(
        actor=request.user if getattr(request.user, "is_authenticated", False) else None,
        action=action,
        content_type=content_type,
        object_id=object_id,
        target_label=derived_label,
        route=request.path,
        ip_address=_request_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        before_state=before_state or {},
        after_state=after_state or {},
        metadata=metadata or {},
    )