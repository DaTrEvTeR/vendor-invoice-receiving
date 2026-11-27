"""Django settings. Everything environment-specific comes from env variables."""

import os
from pathlib import Path

from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent


def env_bool(name: str, default: bool = False) -> bool:
    """Read a 0/1 flag from the environment."""
    return os.environ.get(name, "1" if default else "0") == "1"


def env_list(name: str, default: str) -> list[str]:
    """Read a comma-separated list from the environment."""
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG")

# No key configured means an ephemeral random key: safe by default, and sessions
# simply do not survive a restart. Any real deployment must set DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or get_random_secret_key()

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "receiving",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {
            # Every transaction takes the write lock up front, so concurrent writers
            # queue instead of failing halfway (select_for_update is a no-op on SQLite).
            "transaction_mode": "IMMEDIATE",
            "timeout": int(os.environ.get("DJANGO_DB_TIMEOUT", "20")),
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# Reference data shipped with the project (catalog, vendors, POs, sample invoices).
DATA_DIR = Path(os.environ.get("RECEIVING_DATA_DIR", str(REPO_ROOT / "data")))
# Where build_outcomes writes outcomes.json.
RESULTS_DIR = Path(os.environ.get("RECEIVING_RESULTS_DIR", str(REPO_ROOT / "results")))
# Largest invoice file accepted, in bytes.
MAX_UPLOAD_BYTES = int(os.environ.get("RECEIVING_MAX_UPLOAD_BYTES", str(1024 * 1024)))

REST_FRAMEWORK = {
    # Dev-only: the API has no authentication yet (see DECISIONS.md, Security).
    # With no authentication classes there is no session, so no CSRF either.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    # Use-case errors (refused upload, invalid transition, blocking issues) become 400/409 with reasons.
    "EXCEPTION_HANDLER": "receiving.api.exceptions.handler",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "loggers": {
        "receiving": {"handlers": ["console"], "level": "INFO", "propagate": True},
    },
}
