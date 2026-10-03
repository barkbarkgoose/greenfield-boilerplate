"""Base settings for config project."""

import sys
from datetime import timedelta
from pathlib import Path

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
    get as keychain_get,
    get_int as keychain_get_int,
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
# Shop-local time zone: appointment times in emails and the admin use it.
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
        "rest_framework_simplejwt.authentication.JWTAuthentication",
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
        "intake_parts": "240/hour",
        # Open garage pages check for replies every ~15s while visible.
        "garage_poll": "1200/hour",
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

BUSINESS_NAME = env("BUSINESS_NAME", default="Wrench on Wheels")

# Public URL of the frontend, used for links inside emails.
SITE_URL = (_keychain_or_env("SITE_URL", "SITE_URL", default="http://localhost:5177") or "").rstrip("/")

# --- Parts estimates -----------------------------------------------------------
# Estimates come from the PartPriceExample table (see apps/intake/parts.py) and
# run on a background thread so the VIN decode never slows down booking.
PARTS_ESTIMATE_ASYNC = True

# --- Captcha (Cloudflare Turnstile) -------------------------------------------
# Leave unset to disable (local dev, tests). Set together with the frontend's
# VITE_TURNSTILE_SITE_KEY.
# Customer <-> mechanic message threads on request pages (and the live-update
# polling that comes with them). Off for launch: customers call or text instead.
# The code, data and tests stay; set INTAKE_MESSAGING_ENABLED=1 to bring it back.
INTAKE_MESSAGING_ENABLED = env.bool("INTAKE_MESSAGING_ENABLED", default=False)

TURNSTILE_SECRET_KEY = _keychain_or_env("TURNSTILE_SECRET_KEY", "TURNSTILE_SECRET_KEY", default="")
