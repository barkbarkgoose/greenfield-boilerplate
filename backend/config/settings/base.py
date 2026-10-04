"""Base settings for config project."""

import secrets
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import environ

env = environ.Env()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Make the `keychain` package importable when settings load through a plain
# `python manage.py` invocation (dev.sh already adds backend/ to sys.path).
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

environ.Env.read_env(BASE_DIR / ".env")

from keychain import (  # noqa: E402
    KeychainNotInitializedError,
)
from keychain import (
    get as keychain_get,
)
from keychain import (
    get_int as keychain_get_int,
)
from keychain import (
    get_list as keychain_get_list,
)


def _keychain_or_env(key: str, env_var: str, default: str | None = None) -> str | None:
    """Resolve a scalar setting from the keychain, falling back to the environment.

    The keychain is optional during first-run bootstrap: if it has not been
    initialized, values are read from `.env` so management commands keep working
    before `python -m keychain init`.
    """
    try:
        value = keychain_get(key)
    except KeychainNotInitializedError:
        value = None
    if value is not None:
        return value
    return env(env_var, default=default)


def _keychain_or_env_list(
    key: str, env_var: str, default: list[str] | None = None
) -> list[str]:
    """Resolve a comma-separated list setting from keychain or environment."""
    try:
        value = keychain_get_list(key)
    except KeychainNotInitializedError:
        value = None
    if value is not None:
        return value
    return env.list(env_var, default=default if default is not None else [])


SECRET_KEY = _keychain_or_env("SECRET_KEY", "SECRET_KEY")

DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "corsheaders",
    "apps.organizations",
    "apps.users",
    "apps.intake",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Picks the request language from Accept-Language (sent by the frontend).
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

APPEND_SLASH = False

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

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_URL = _keychain_or_env(
    "DATABASE_URL", "DATABASE_URL", default="sqlite:///db.sqlite3"
)
DATABASES = {"default": env.db_url_config(DATABASE_URL)}

AUTH_USER_MODEL = "users.User"

# Django admin address. Set ADMIN_URL (e.g. "back-office-7f3k2q/") to a hard-to-
# guess path in each environment. Unset, it's random and changes every time the
# server starts (printed in the server log), so the admin is effectively hidden.
# With several server processes (gunicorn workers) each gets its own random path,
# so set ADMIN_URL anywhere you actually use the admin.
_ADMIN_URL = (_keychain_or_env("ADMIN_URL", "ADMIN_URL", default="") or "").strip().strip("/")
ADMIN_URL_IS_RANDOM = not _ADMIN_URL
ADMIN_URL = (_ADMIN_URL or f"admin-{secrets.token_urlsafe(16)}") + "/"

# Password reset links work once and expire after this many seconds. The
# customer-facing text says "2 hours" (auth-forgot__sent, auth-reset__invalid).
PASSWORD_RESET_TIMEOUT = 2 * 60 * 60

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
# Customer-facing languages. Text lives in apps/intake/text/*.json and the
# frontend's src/i18n/locales/*.json; see the README's "Translations".
LANGUAGES = [("en", "English"), ("es", "Español")]
# Yard-local time zone: delivery dates in emails and the admin use it.
TIME_ZONE = env("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = _keychain_or_env_list(
    "CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_ORIGINS"
)

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.users.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    # Only views that set `throttle_scope` are throttled (the public intake form).
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "intake_estimate": "120/hour",
        "intake_submit": "10/hour",
        "intake_message": "30/hour",
        "intake_claim": "20/hour",
        # Open order pages check for replies every ~10s while visible.
        "account_poll": "1200/hour",
        # Per IP: slows password guessing and reset-email spam.
        "auth_login": "30/hour",
        "password_reset": "5/hour",
        "password_reset_confirm": "20/hour",
    },
}


def _jwt_lifetimes() -> tuple[timedelta, timedelta]:
    """Resolve JWT lifetimes from the keychain, falling back to safe defaults.

    These are read from the keychain so token lifetimes can be tuned per
    environment without editing code. Falls back to 60 minutes / 7 days when the
    keychain has not been initialized yet (e.g. during the first migration).
    """
    try:
        access_minutes = (
            keychain_get_int("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=60) or 60
        )
    except KeychainNotInitializedError:
        access_minutes = 60
    try:
        refresh_days = (
            keychain_get_int("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7) or 7
        )
    except KeychainNotInitializedError:
        refresh_days = 7
    return timedelta(minutes=access_minutes), timedelta(days=refresh_days)


_ACCESS_LIFETIME, _REFRESH_LIFETIME = _jwt_lifetimes()

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": _ACCESS_LIFETIME,
    "REFRESH_TOKEN_LIFETIME": _REFRESH_LIFETIME,
}

# Staff sessions are shorter (see apps/users/tokens.py): access tokens renew
# silently every 15 minutes, and staff sign in again after 8 hours.
STAFF_ACCESS_TOKEN_LIFETIME = timedelta(minutes=env.int("STAFF_ACCESS_TOKEN_MINUTES", default=15))
STAFF_SESSION_LIFETIME = timedelta(hours=env.int("STAFF_SESSION_HOURS", default=8))

# --- Email -------------------------------------------------------------------
# SMTP by default; local/test settings override the backend. Credentials come
# from the keychain so they never live in .env.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = _keychain_or_env("EMAIL_HOST", "EMAIL_HOST", default="localhost")
EMAIL_PORT = int(_keychain_or_env("EMAIL_PORT", "EMAIL_PORT", default="587"))
EMAIL_HOST_USER = _keychain_or_env("EMAIL_HOST_USER", "EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = _keychain_or_env(
    "EMAIL_HOST_PASSWORD", "EMAIL_HOST_PASSWORD", default=""
)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = _keychain_or_env(
    "DEFAULT_FROM_EMAIL", "DEFAULT_FROM_EMAIL", default="webmaster@localhost"
)

# Where "new request" and "customer replied" notifications go.
INTAKE_NOTIFY_EMAILS = _keychain_or_env_list("INTAKE_NOTIFY_EMAILS", "INTAKE_NOTIFY_EMAILS")

BUSINESS_NAME = env("BUSINESS_NAME", default="Groundwork Soil & Supply")

# Public URL of the frontend, used for links inside emails.
SITE_URL = (_keychain_or_env("SITE_URL", "SITE_URL", default="http://localhost:5177") or "").rstrip("/")

# Passkeys (apps/users/passkeys.py). Required per account with
# User.passkey_required; PASSKEYS_ENABLED=False switches that off everywhere.
# A passkey belongs to PASSKEY_RP_ID (the site's domain, from SITE_URL) and is
# only accepted from PASSKEY_ORIGINS, so each environment has its own.
PASSKEYS_ENABLED = env.bool("PASSKEYS_ENABLED", default=True)
PASSKEY_RP_ID = env("PASSKEY_RP_ID", default="") or (urlparse(SITE_URL).hostname or "localhost")
PASSKEY_RP_NAME = env("PASSKEY_RP_NAME", default="") or BUSINESS_NAME
PASSKEY_ORIGINS = env.list("PASSKEY_ORIGINS", default=[SITE_URL])

# --- Service area -----------------------------------------------------------
# The zip-code lookup table (see apps/intake/service_area.py). Blank = the
# bundled apps/intake/data/service_area.json.
SERVICE_AREA_FILE = env("SERVICE_AREA_FILE", default="")

# --- Captcha (Cloudflare Turnstile) -------------------------------------------
# Leave unset to disable (local dev, tests). Set together with the frontend's
# VITE_TURNSTILE_SITE_KEY.
# Customer <-> staff message threads on order pages (and the live-update
# polling that comes with them). Off for launch: customers call or text instead.
# The code, data and tests stay; set INTAKE_MESSAGING_ENABLED=1 to bring it back.
INTAKE_MESSAGING_ENABLED = env.bool("INTAKE_MESSAGING_ENABLED", default=False)

TURNSTILE_SECRET_KEY = _keychain_or_env("TURNSTILE_SECRET_KEY", "TURNSTILE_SECRET_KEY", default="")
