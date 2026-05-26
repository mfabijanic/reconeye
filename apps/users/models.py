from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model — allows future extension without migrations hassle."""

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
