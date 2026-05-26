"""Expose Celery app for `celery -A config.celery` CLI."""
from config.celery import app as celery_app  # noqa: F401

__all__ = ["celery_app"]
