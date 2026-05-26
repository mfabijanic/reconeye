from django.apps import AppConfig


class ScrapingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.scraping"
    verbose_name = "Scraping"

    def ready(self):
        import apps.scraping.signals  # noqa: F401
