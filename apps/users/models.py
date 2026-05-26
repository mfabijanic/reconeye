from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model — allows future extension without migrations hassle."""

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"


class UserMapSettings(models.Model):
    """Per-user overrides for map behavior. Empty values use global defaults."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="map_settings",
    )
    disable_clustering_at_zoom = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(2), MaxValueValidator(18)],
        help_text="Override cluster expansion zoom level. Empty = global default.",
    )
    marker_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(100), MaxValueValidator(5000)],
        help_text="Override max markers per map request. Empty = global default.",
    )
    status_stale_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(1440)],
        help_text="Override stale-status threshold in minutes. Empty = global default.",
    )
    popup_close_on_mouseout = models.BooleanField(
        null=True,
        blank=True,
        help_text="Override popup auto-close on mouseout. Empty = global default.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Map Settings"
        verbose_name_plural = "User Map Settings"

    def __str__(self) -> str:
        return f"Map settings for {self.user.username}"
