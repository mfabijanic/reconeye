"""
Django settings — base configuration shared across all environments.
"""
import json
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)

# Read .env file if present
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Application definition
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "django_celery_beat",
    "django_celery_results",
    "django_htmx",
]

LOCAL_APPS = [
    "apps.common",
    "apps.users",
    "apps.cameras",
    "apps.scraping",
    "apps.dashboard",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.common.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database
DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://reconeye:reconeye@localhost:5432/reconeye")
}
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["OPTIONS"] = {"connect_timeout": 10}

# Cache
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_URL", default="redis://localhost:6379/3"),
        "KEY_PREFIX": "reconeye",
        "VERSION": 1,
        "TIMEOUT": env.int("CACHE_DEFAULT_TIMEOUT", default=120),
    }
}

# Auth
AUTH_USER_MODEL = "users.User"
LOGIN_URL = "/users/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/users/login/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static / Media
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")
CELERY_RESULT_BACKEND_DB = "django-db"
CELERY_CACHE_BACKEND = "django-cache"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 60  # 1 hour hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 55 * 60
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True

# Security headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Session
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8 hours

# Scraping configuration
# Complete list fetched from http://www.insecam.org/en/jsoncountries/ (2026-05-26)
# Override via .env: INSECAM_COUNTRY_CODES=US,JP,DE,...
# All countries available on Insecam (sorted by camera count) — see apps/scraping/config.py
INSECAM_COUNTRY_CODES = env.list(
    "INSECAM_COUNTRY_CODES",
    default=[
        "US", "JP", "IT", "DE", "RU", "AT", "CZ", "FR", "KR", "CH",
        "NO", "RO", "TW", "CA", "ES", "SE", "NL", "PL", "GB", "UA",
        "RS", "BG", "DK", "IN", "SK", "FI", "BE", "HU", "ZA", "TR",
        "GR", "BA", "TH", "BR", "EG", "NZ", "IE", "AU", "ID", "CL",
        "AR", "CN", "LT", "SI", "MX", "KZ", "MD", "EE", "VN", "FO",
        "HN", "HK", "IL", "BY", "PE", "GU", "PA", "BD", "AM", "SG",
        "NI", "CO", "-",
    ],
)
WHATSUPCAMS_COUNTRY_CODES = env.list(
    "WHATSUPCAMS_COUNTRY_CODES",
    default=["BA", "DO", "ES", "GR", "HR", "IE", "IT", "MK", "NL", "SI"],
)
ENABLE_PERIODIC_SCRAPING = env.bool("ENABLE_PERIODIC_SCRAPING", default=False)
ENABLE_PERIODIC_WUC_BY_COUNTRY = env.bool("ENABLE_PERIODIC_WUC_BY_COUNTRY", default=False)
PERIODIC_WUC_BASE_HOUR = env.int("PERIODIC_WUC_BASE_HOUR", default=4)
PERIODIC_WUC_MINUTE_STEP = env.int("PERIODIC_WUC_MINUTE_STEP", default=5)
_WUC_COUNTRY_CRON_OVERRIDES_RAW = env("PERIODIC_WUC_COUNTRY_CRON_OVERRIDES", default="")
try:
    PERIODIC_WUC_COUNTRY_CRON_OVERRIDES: dict[str, str | list[int] | tuple[int, int]] = (
        json.loads(_WUC_COUNTRY_CRON_OVERRIDES_RAW) if _WUC_COUNTRY_CRON_OVERRIDES_RAW else {}
    )
except (TypeError, ValueError):
    PERIODIC_WUC_COUNTRY_CRON_OVERRIDES = {}
NOMINATIM_USER_AGENT = env(
    "NOMINATIM_USER_AGENT",
    default="reconeye/1.0 (contact: admin@localhost)",
)
WUC_STREAM_PREFIX_OVERRIDES: dict[str, str] = {}
WUC_STREAM_LOCATION_OVERRIDES: dict[str, str] = {}
GO2RTC_BASE_URL = env("GO2RTC_BASE_URL", default="http://127.0.0.1:1984")

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Login-required middleware exempt paths
LOGIN_EXEMPT_URLS = [
    "/users/login/",
    "/users/logout/",
    "/health/",
    "/readiness/",
    "/admin/",
]
