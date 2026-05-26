from django.apps import AppConfig


class CamerasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cameras"
    verbose_name = "Cameras"

    def ready(self):
        import apps.cameras.signals  # noqa: F401
