from .base import *  # noqa: F401, F403
from pathlib import Path

DEBUG = True

INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405

MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE  # noqa: F405

INTERNAL_IPS = ["127.0.0.1"]

# Relaxed security for local dev
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Local developer defaults (no external services required)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATABASES = {
	"default": {
		"ENGINE": "django.db.backends.sqlite3",
		"NAME": BASE_DIR / "db.sqlite3",
	}
}

CACHES = {
	"default": {
		"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
		"LOCATION": "reconeye-dev-cache",
		"TIMEOUT": 120,
	}
}

SESSION_ENGINE = "django.contrib.sessions.backends.db"
