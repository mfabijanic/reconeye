from __future__ import annotations

from django.contrib.auth.models import Group
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.common.authz import ROLE_GROUPS


@receiver(post_migrate)
def ensure_default_role_groups(sender, **kwargs):
    app_config = kwargs.get("app_config")
    if app_config and app_config.name != "apps.common":
        return

    for role in ROLE_GROUPS:
        Group.objects.get_or_create(name=role)